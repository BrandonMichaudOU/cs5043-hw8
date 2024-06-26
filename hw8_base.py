'''
Advanced Machine Learning, 2024
HW 5 Base Code

Author: Andrew H. Fagg (andrewhfagg@gmail.com)

Image classification for the Core 50 data set

Updates for using caching and GPUs
- Batch file:
#SBATCH --gres=gpu:1
#SBATCH --partition=gpu
or
#SBATCH --partition=disc_dual_a100_students
#SBATCH --cpus-per-task=64

- Command line options to include
--cache $LSCRATCH                              (use lscratch to cache the datasets to local fast disk)
--batch 4096                                   (this parameter is per GPU)
--gpu
--precache datasets_by_fold_4_objects          (use a 4-object pre-constructed dataset)

Notes: 
- batch is now a parameter per GPU.  If there are two GPUs, then this number is doubled internally.
   Note that you must do other things to make use of more than one GPU
- 4096 works on the a100 GPUs
- The prcached dataset is a serialized copy of a set of TF.Datasets (located on slow spinning disk).  
Each directory contains all of the images for a single data fold within a couple of files.  Loading 
these files is *a lot* less expensive than having to load the individual images and preprocess them 
at the beginning of a run.
- The cache is used to to store the loaded datasets onto fast, local SSD so they can be fetched quickly
for each training epoch

'''
import wandb
import socket
import tensorflow as tf

from tensorflow.keras.utils import plot_model
from tensorflow import keras

# Provided
from chesapeake_loader4 import *
from hw8_parser import *

# You need to provide this yourself
from diffusion_model import *


def generate_fname(args):
    '''
    Generate the base file name for output files/directories.
    
    The approach is to encode the key experimental parameters in the file name.  This
    way, they are unique and easy to identify after the fact.

    :param args: from argParse
    '''
    return f'{args.results_path}/{args.exp_type}{f"_{args.label}" if args.label is not None else ""}'


def execute_exp(args=None, multi_gpus=False):
    '''
    Perform the training and evaluation for a single model
    
    :param args: Argparse arguments
    :param multi_gpus: True if there are more than one GPU
    '''

    # Check the arguments
    if args is None:
        # Case where no args are given (usually, because we are calling from within Jupyter)
        #  In this situation, we just use the default arguments
        parser = create_parser()
        args = parser.parse_args([])

    # Scale the batch size with the number of GPUs
    if multi_gpus > 1:
        args.batch = args.batch * multi_gpus

    print('Batch size', args.batch)

    if args.verbose >= 3:
        print('Starting data flow')

    # Compute noise schedule
    beta, alpha, _ = compute_beta_alpha2(args.n_steps, args.beta_start, args.beta_end)

    # Load dataset
    if not args.no_data:
        ds_train, ds_valid = create_diffusion_dataset(base_dir=args.dataset,
                                                      patch_size=args.image_size,
                                                      fold=args.fold,
                                                      cache_dir=args.cache,
                                                      repeat=args.repeat,
                                                      shuffle=args.shuffle,
                                                      batch_size=args.batch,
                                                      prefetch=args.prefetch,
                                                      num_parallel_calls=args.num_parallel_calls,
                                                      alpha=alpha)
    else:
        ds_train, ds_valid = None, None

    # Build the model
    if args.verbose >= 3:
        print('Building network')

    # Create the network
    if multi_gpus > 1:
        # Multiple GPUs
        mirrored_strategy = tf.distribute.MirroredStrategy()

        with mirrored_strategy.scope():
            # Build network: you must provide your own implementation
            model = create_diffusion_model(image_size=(args.image_size, args.image_size),
                                           n_channels=args.n_channels,
                                           n_classes=args.n_classes,
                                           n_steps=args.n_steps,
                                           n_embedding=args.n_embedding,
                                           filters=args.filters,
                                           n_conv_per_step=args.n_conv_per_step,
                                           conv_activation=args.conv_activation,
                                           kernel_size=args.kernel_size,
                                           padding=args.padding,
                                           sdropout=args.sdropout,
                                           batch_normalization=args.batch_normalization)
    else:
        # Single GPU
        # Build network: you must provide your own implementation
        model = create_diffusion_model(image_size=(args.image_size, args.image_size),
                                       n_channels=args.n_channels,
                                       n_classes=args.n_classes,
                                       n_steps=args.n_steps,
                                       n_embedding=args.n_embedding,
                                       filters=args.filters,
                                       n_conv_per_step=args.n_conv_per_step,
                                       conv_activation=args.conv_activation,
                                       kernel_size=args.kernel_size,
                                       padding=args.padding,
                                       sdropout=args.sdropout,
                                       batch_normalization=args.batch_normalization)

    # Compile the model
    opt = tf.keras.optimizers.Adam(learning_rate=args.lrate, amsgrad=False)
    model.compile(loss=tf.keras.losses.MeanSquaredError(), optimizer=opt, metrics=None)

    # Report model structure if verbosity is turned on
    if args.verbose >= 1 and model is not None:
        print(model.summary())

    print(args)

    # Output file base and pkl file
    fbase = generate_fname(args)
    print(fbase)
    fname_out = "%s_results.pkl" % fbase

    # Plot the model
    if args.render:
        render_fname = '%s_model_plot.png' % fbase
        plot_model(model, to_file=render_fname, show_shapes=True, show_layer_names=True)

    # Perform the experiment?
    if args.nogo:
        # No!
        print("NO GO")
        print(fbase)
        return

    # Check if output file already exists
    if not args.force and os.path.exists(fname_out):
        # Results file does exist: exit
        print("File %s already exists" % fname_out)
        return

    #####
    # Start wandb
    run = wandb.init(project=args.project, name=f'{args.exp_type}', notes=fbase, config=vars(args))

    # Log hostname
    wandb.log({'hostname': socket.gethostname()})

    # Log model design image
    if args.render:
        wandb.log({'model architecture': wandb.Image(render_fname)})

    # Callbacks
    cbs = []
    early_stopping_cb = keras.callbacks.EarlyStopping(patience=args.patience, restore_best_weights=True,
                                                      min_delta=args.min_delta, monitor=args.monitor)
    cbs.append(early_stopping_cb)

    # Weights and Biases
    wandb_metrics_cb = wandb.keras.WandbMetricsLogger()
    cbs.append(wandb_metrics_cb)

    if args.verbose >= 3:
        print('Fitting model')

    # Learn
    history = model.fit(ds_train,
                        epochs=args.epochs,
                        steps_per_epoch=args.steps_per_epoch,
                        use_multiprocessing=True,
                        verbose=args.verbose >= 2,
                        validation_data=ds_valid,
                        callbacks=cbs)

    # Save model
    if args.save_model:
        model.save("%s_model" % (fbase))

    wandb.finish()

    return model


if __name__ == "__main__":
    # Parse and check incoming arguments
    parser = create_parser()
    args = parser.parse_args()

    if args.verbose >= 3:
        print('Arguments parsed')

    # Turn off GPU?
    if not args.gpu or "CUDA_VISIBLE_DEVICES" not in os.environ.keys():
        tf.config.set_visible_devices([], 'GPU')
        print('NO VISIBLE DEVICES!!!!')

    # GPU check
    visible_devices = tf.config.get_visible_devices('GPU')
    n_visible_devices = len(visible_devices)
    print('GPUS:', visible_devices)
    if n_visible_devices > 0:
        for device in visible_devices:
            tf.config.experimental.set_memory_growth(device, True)
        print('We have %d GPUs\n' % n_visible_devices)
    else:
        print('NO GPU')

    # Set number of threads, if it is specified
    if args.cpus_per_task is not None:
        tf.config.threading.set_intra_op_parallelism_threads(args.cpus_per_task)
        tf.config.threading.set_inter_op_parallelism_threads(args.cpus_per_task)

    execute_exp(args, multi_gpus=n_visible_devices)
