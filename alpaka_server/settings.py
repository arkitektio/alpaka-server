"""
Django settings for mikro_server project.

Generated by 'django-admin startproject' using Django 4.2.3.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/4.2/ref/settings/
"""

from pathlib import Path
import os
from omegaconf import OmegaConf


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
conf = OmegaConf.load(os.path.join(BASE_DIR, "config.yaml"))

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = "django-insecure-6vh8x**%4mm0yxjbghipsalf5$wum10_satqhxg$vo9jninehx"

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS: list[str] = ["*"]


# Application definition

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "channels_redis",
    "guardian",
    "simple_history",
    "authentikate",
    "koherent",
    "kante",
    "channels",
    "django_probes",
    "kammer",
    "llm",
    "vector",
    "health_check",  # required for health checks
    "health_check.db",  # stock Django health checkers
]


AUTH_USER_MODEL = "authentikate.User"


GRAPHENE = {"SCHEMA": "core.schema.schema"}

CHANNEL_LAYERS = {
    "default": {
        # This example app uses the Redis channel layer implementation channels_redis
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [(conf.redis.host, conf.redis.port)], "prefix": "mikro"},
    },
}


OLLAMA_URL = conf.get("ollama_url", "http://ollama:11434")
CHROMA_DB_HOST = conf.get("chroma_db_host", "chromadb")
CHROMA_DB_PORT = conf.get("chroma_db_port", 8000)

CORS_ALLOW_ALL_ORIGINS = True


STRAWBERRY_DJANGO = {
    "FIELD_DESCRIPTION_FROM_HELP_TEXT": True,
    "TYPE_DESCRIPTION_FROM_MODEL_DOCSTRING": True,
    "USE_DEPRECATED_FILTERS": True,
}


MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "alpaka_server.urls"
MY_SCRIPT_NAME = conf.get("force_script_name", "")

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

AUTHENTICATION_BACKENDS = (
    "django.contrib.auth.backends.ModelBackend",  # this is default
    "guardian.backends.ObjectPermissionBackend",
)

WSGI_APPLICATION = "alpaka_server.wsgi.application"
ASGI_APPLICATION = "alpaka_server.asgi.application"


# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": conf.db.engine,
        "NAME": conf.db.db_name,
        "USER": conf.db.username,
        "PASSWORD": conf.db.password,
        "HOST": conf.db.host,
        "PORT": conf.db.port,
    }
}

# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",  # noqa: E501
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


AUTHENTIKATE = {
    "ISSUERS": [
        {
            "iss": "lok",
            "kind": "rsa",
            "public_key": conf.lok.get("public_key", None),
        }
    ],
    "STATIC_TOKENS": conf.lok.get("static_tokens", {}),
}


# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"redis://{conf.redis.host}:{conf.redis.port}/1",
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
        "KEY_PREFIX": "kluster_server_cache",
    }
}


CACHE_TTL_DEFAULT = 60 * 15


LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = "static/"

# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
