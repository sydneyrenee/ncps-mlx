"""JSON utilities for legacy saving formats (h5 and SavedModel)"""

import collections
import enum
import functools
import json

try:
    import mlx.core as np
    BackendArray = np.array
except ImportError:
    import numpy as np
    BackendArray = np.ndarray
    
from ncps.mini_keras.legacy.saving import serialization
from ncps.mini_keras.saving import serialization_lib
from ncps.mini_keras.utils.module_utils import tensorflow as tf

_EXTENSION_TYPE_SPEC = "_EXTENSION_TYPE_SPEC"


class Encoder(json.JSONEncoder):
    """JSON encoder and decoder that handles TensorShapes and tuples."""

    def default(self, obj):
        """Encodes objects for types that aren't handled by the default
        encoder."""
        if tf.available and isinstance(obj, tf.TensorShape):
            items = obj.as_list() if obj.rank is not None else None
            return {"class_name": "TensorShape", "items": items}
        return get_json_type(obj)

    def encode(self, obj):
        return super().encode(_encode_tuple(obj))


def _encode_tuple(x):
    if isinstance(x, tuple):
        return {
            "class_name": "__tuple__",
            "items": tuple(_encode_tuple(i) for i in x),
        }
    elif isinstance(x, list):
        return [_encode_tuple(i) for i in x]
    elif isinstance(x, dict):
        return {key: _encode_tuple(value) for key, value in x.items()}
    else:
        return x


def decode(json_string):
    return json.loads(json_string, object_hook=_decode_helper)


def decode_and_deserialize(
    json_string, module_objects=None, custom_objects=None
):
    """Decodes the JSON and deserializes any Keras objects found in the dict."""
    return json.loads(
        json_string,
        object_hook=functools.partial(
            _decode_helper,
            deserialize=True,
            module_objects=module_objects,
            custom_objects=custom_objects,
        ),
    )


def _decode_helper(
    obj, deserialize=False, module_objects=None, custom_objects=None
):
    """A decoding helper that is TF-object aware.

    Args:
      obj: A decoded dictionary that may represent an object.
      deserialize: Boolean. When True, deserializes any Keras
        objects found in `obj`. Defaults to `False`.
      module_objects: A dictionary of built-in objects to look the name up in.
        Generally, `module_objects` is provided by midlevel library
        implementers.
      custom_objects: A dictionary of custom objects to look the name up in.
        Generally, `custom_objects` is provided by the end user.

    Returns:
      The decoded object.
    """
    if isinstance(obj, dict) and "class_name" in obj:
        if tf.available:
            if obj["class_name"] == "TensorShape":
                return tf.TensorShape(obj["items"])
            elif obj["class_name"] == "TypeSpec":
                from tensorflow.python.framework import type_spec_registry

                return type_spec_registry.lookup(obj["type_spec"])._deserialize(
                    _decode_helper(obj["serialized"])
                )
            elif obj["class_name"] == "CompositeTensor":
                spec = obj["spec"]
                tensors = []
                for dtype, tensor in obj["tensors"]:
                    tensors.append(
                        tf.constant(tensor, dtype=tf.dtypes.as_dtype(dtype))
                    )
                return tf.nest.pack_sequence_as(
                    _decode_helper(spec), tensors, expand_composites=True
                )

        if obj["class_name"] == "__tuple__":
            return tuple(_decode_helper(i) for i in obj["items"])
        elif obj["class_name"] == "__ellipsis__":
            return Ellipsis
        elif deserialize and "__passive_serialization__" in obj:
            # __passive_serialization__ is added by the JSON encoder when
            # encoding an object that has a `get_config()` method.
            try:
                if (
                    "module" not in obj
                ):  # TODO(nkovela): Add TF SavedModel scope
                    return serialization.deserialize_keras_object(
                        obj,
                        module_objects=module_objects,
                        custom_objects=custom_objects,
                    )
                else:
                    return serialization_lib.deserialize_keras_object(
                        obj,
                        module_objects=module_objects,
                        custom_objects=custom_objects,
                    )
            except ValueError:
                pass
        elif obj["class_name"] == "__bytes__":
            return obj["value"].encode("utf-8")
    return obj


def get_json_type(obj):
    """Serializes any object to a JSON-serializable structure.

    Args:
        obj: the object to serialize

    Returns:
        JSON-serializable structure representing `obj`.

    Raises:
        TypeError: if `obj` cannot be serialized.
    """
    # if obj is a serializable Keras class instance
    # e.g. optimizer, layer
    if hasattr(obj, "get_config"):
        # TODO(nkovela): Replace with legacy serialization
        serialized = serialization.serialize_keras_object(obj)
        serialized["__passive_serialization__"] = True
        return serialized

    # if obj is any numpy type
    if type(obj).__module__ == np.__name__:
        if isinstance(obj, BackendArray):
            return obj.tolist()
        else:
            return obj.item()

    # misc functions (e.g. loss function)
    if callable(obj):
        return obj.__name__

    # if obj is a python 'type'
    if type(obj).__name__ == type.__name__:
        return obj.__name__

    if tf.available and isinstance(obj, tf.compat.v1.Dimension):
        return obj.value

    if tf.available and isinstance(obj, tf.TensorShape):
        return obj.as_list()

    if tf.available and isinstance(obj, tf.DType):
        return obj.name

    if isinstance(obj, collections.abc.Mapping):
        return dict(obj)

    if obj is Ellipsis:
        return {"class_name": "__ellipsis__"}

    # if isinstance(obj, wrapt.ObjectProxy):
    #     return obj.__wrapped__

    if tf.available and isinstance(obj, tf.TypeSpec):
        from tensorflow.python.framework import type_spec_registry

        try:
            type_spec_name = type_spec_registry.get_name(type(obj))
            return {
                "class_name": "TypeSpec",
                "type_spec": type_spec_name,
                "serialized": obj._serialize(),
            }
        except ValueError:
            raise ValueError(
                f"Unable to serialize {obj} to JSON, because the TypeSpec "
                f"class {type(obj)} has not been registered."
            )
    if tf.available and isinstance(obj, tf.__internal__.CompositeTensor):
        spec = tf.type_spec_from_value(obj)
        tensors = []
        for tensor in tf.nest.flatten(obj, expand_composites=True):
            tensors.append((tensor.dtype.name, tensor.numpy().tolist()))
        return {
            "class_name": "CompositeTensor",
            "spec": get_json_type(spec),
            "tensors": tensors,
        }

    if isinstance(obj, enum.Enum):
        return obj.value

    if isinstance(obj, bytes):
        return {"class_name": "__bytes__", "value": obj.decode("utf-8")}

    raise TypeError(
        f"Unable to serialize {obj} to JSON. Unrecognized type {type(obj)}."
    )
