import ncps.mini_keras.backend
from ncps.mini_keras import tree
from ncps.mini_keras.layers.layer import Layer
from ncps.mini_keras.random.seed_generator import SeedGenerator
from ncps.mini_keras.utils import backend_utils
from ncps.mini_keras.utils import jax_utils
from ncps.mini_keras.utils import tracking


class TFDataLayer(Layer):
    """Layer that can safely used in a tf.data pipeline.

    The `call()` method must solely rely on `self.backend` ops.

    Only supports a single input tensor argument.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.backend = backend_utils.DynamicBackend()
        self._allow_non_tensor_positional_args = True

    def __call__(self, inputs, **kwargs):
        sample_input = tree.flatten(inputs)[0]
        if (
            not isinstance(sample_input, keras.KerasTensor)
            and backend_utils.in_tf_graph()
            and not jax_utils.is_in_jax_tracing_scope(sample_input)
        ):
            # We're in a TF graph, e.g. a tf.data pipeline.
            self.backend.set_backend("tensorflow")
            inputs = tree.map_structure(
                lambda x: self.backend.convert_to_tensor(
                    x, dtype=self.compute_dtype
                ),
                inputs,
            )
            switch_convert_input_args = False
            if self._convert_input_args:
                self._convert_input_args = False
                switch_convert_input_args = True
            try:
                outputs = super().__call__(inputs, **kwargs)
            finally:
                self.backend.reset()
                if switch_convert_input_args:
                    self._convert_input_args = True
            return outputs
        return super().__call__(inputs, **kwargs)

    @tracking.no_automatic_dependency_tracking
    def _get_seed_generator(self, backend=None):
        if backend is None or backend == keras.backend.backend():
            return self.generator
        if not hasattr(self, "_backend_generators"):
            self._backend_generators = {}
        if backend in self._backend_generators:
            return self._backend_generators[backend]
        seed_generator = SeedGenerator(self.seed, backend=self.backend)
        self._backend_generators[backend] = seed_generator
        return seed_generator

    def convert_weight(self, weight):
        """Convert the weight if it is from the a different backend."""
        if self.backend.name == keras.backend.backend():
            return weight
        else:
            weight = keras.ops.convert_to_numpy(weight)
            return self.backend.convert_to_tensor(weight)
