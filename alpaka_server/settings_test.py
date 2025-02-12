from .settings import *  # noqa
from .settings import DATABASES

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "mydatabase",  # This is where you put the name of the db file.
        # If one doesn't exist, it will be created at migration time.
    }
}

CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
