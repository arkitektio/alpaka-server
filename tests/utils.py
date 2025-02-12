import os


def build_relative_dir(path: str) -> str:
    """Build a relative directory from a path

    Parameters
    ----------
    path : str
        The path to build a relative directory from

    Returns
    -------
    str
        The relative directory
    """
    return os.path.join(os.path.dirname(__file__), path)
