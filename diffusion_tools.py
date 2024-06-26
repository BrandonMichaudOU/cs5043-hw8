import numpy as np
import tensorflow as tf
from tensorflow import keras

def compute_beta_alpha(nsteps, beta_start, beta_end, gamma_start=0, gamma_end=0.1):
    '''
    Create the beta, alpha and gamma sequences.
    Element 0 is closest to the true image; element NSTEPS-1 is closest to the
       completely noised image
       
    '''
    beta = np.arange(beta_start, beta_end, (beta_end-beta_start)/nsteps)
    sigma = np.arange(gamma_start, gamma_end, (gamma_end-gamma_start)/nsteps)
    alpha = np.cumprod(1-beta)

    return beta, alpha, sigma

def compute_beta_alpha2(nsteps, beta_start, beta_end, gamma_start=0, gamma_end=0.1):
    '''
    Create the beta, alpha and gamma sequences.

    beta follows a sine shape
    
    Element 0 is closest to the true image; element NSTEPS-1 is closest to the
       completely noised image
       
    '''
    t = (np.pi / 2) * (np.arange(0, 1, 1.0/nsteps)) 
    beta = np.sin(t) * (beta_end-beta_start)+beta_start
    sigma = np.arange(gamma_start, gamma_end, (gamma_end-gamma_start)/nsteps)
    alpha = np.cumprod(1-beta)

    return beta, alpha, sigma

def convert_image(I):
    '''
    Convert an image from a form where the pixel values are nominally in a +/-1 range
    into a range of 0...1
    '''
    I = I/2.0 + 0.5
    I = np.maximum(I, 0.0)
    I = np.minimum(I, 1.0)
    return I


'''

Position Encoder Layer

Creates an Attention-Like Positional encoding.  The input tensor
then selects which rows to return.

Source: Hands-On Machine Learning, p 558

'''
class PositionEncoder(keras.layers.Layer):
    def __init__(self, max_steps:int, max_dims:int, 
                 dtype=tf.float32, **kwargs):
        '''
        Constructor

        :param max_steps: the number of tokens in the sequence
        :param max_dims: the length of the vector used to encode position
                    (must match the token encoding length if "add")
        :param embedding_dtype: The type used for encoding of position
        '''
        # Call superclass constructor
        super().__init__(dtype=dtype, **kwargs)

        # Deal with odd lengths
        if max_dims % 2 == 1: max_dims += 1

        # Create the positional representation
        p, i = np.meshgrid(np.arange(max_steps), np.arange(max_dims // 2))
        pos_emb = np.empty((max_steps, max_dims))
        pos_emb[:, ::2] = np.sin(p / 10000**(2 * i / max_dims)).T
        pos_emb[:, 1::2] = np.cos(p / 10000**(2 * i / max_dims)).T

        # Save the state
        self.positional_embedding = tf.constant(pos_emb.astype(self.dtype))

        self.max_steps = max_steps
        self.max_dims = max_dims
        
    def call(self, indices):
        '''
        This method is what implements the object "callable" property.

        Determines how the input tensor is translated into the output tensor.

        :param inputs: TF Tensor that indicates which rows
        :return: TF Tensor
        '''
        return tf.gather_nd(self.positional_embedding, indices)

    def embedding(self):
        return self.positional_embedding

    def get_config(self):
        config = super().get_config()
        config.update({
            "max_steps": self.max_steps,
            "max_dims": self.max_dims,
        })
        return config

    @classmethod
    def from_config(cls, config):
        # Seems to be about serializing sub-objects
        return cls(**config)

        #sublayer_config = config.pop("sublayer")
        #sublayer = keras.saving.deserialize_keras_object(sublayer_config)
        #return cls(sublayer, **config)
