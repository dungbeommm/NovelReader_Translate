"""Apply the notebook's runtime settings safely."""
import os


def apply_runtime_environment(settings: dict, has_gpu: bool):
    os.environ.update(settings)
    if not has_gpu:
        # str("0") is true in Python: never let an absent GPU look present.
        os.environ.pop("COLAB_GPU", None)
