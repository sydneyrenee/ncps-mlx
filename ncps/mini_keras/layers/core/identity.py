from ncps.mini_keras import tree
from ncps.mini_keras.api_export import keras_mini_export
from ncps.mini_keras.backend import KerasTensor
from ncps.mini_keras.layers.layer import Layer


@keras_mini_export("ncps.mini_keras.layers.Identity")
class Identity(Layer):
    """Identity layer.

    This layer should be used as a placeholder when no operation is to be
    performed. The layer just returns its `inputs` argument as output.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.supports_masking = True
        self.built = True

    def call(self, inputs):
        return inputs

    def compute_output_shape(self, input_shape):
        return input_shape

    def compute_output_spec(self, inputs):
        return tree.map_structure(
            lambda x: KerasTensor(x.shape, dtype=x.dtype, sparse=x.sparse),
            inputs,
        )
