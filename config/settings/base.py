from pathlib import Path
from decouple import config
from datetime import timedelta
# -----------------------------------------------------------------------------
# PATHS
# -----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent
# -----------------------------------------------------------------------------
# CORE SETTINGS
# -----------------------------------------------------------------------------
SECRET_KEY = config("SECRET_KEY")
DEBUG = str(config("DEBUG", default="false")).strip().lower() in {"1", "true", "yes", "on", "debug"}
ALLOWED_HOSTS = ["*"]
# -----------------------------------------------------------------------------
# APPLICATIONS
# -----------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]
THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
]
LOCAL_APPS = [
    "apps.accounts",
    "apps.landing",
    "apps.common",
    "apps.notifications",
    "apps.core",
]
INSTALLED_APPS = (
    DJANGO_APPS
    + THIRD_PARTY_APPS
    + LOCAL_APPS
)
# -----------------------------------------------------------------------------
# MIDDLEWARE
# -----------------------------------------------------------------------------
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
# -----------------------------------------------------------------------------
# TEMPLATES
# -----------------------------------------------------------------------------
TEMPLATES = [
    {
        "BACKEND":
            "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            BASE_DIR / "templates",
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
# -----------------------------------------------------------------------------
# DATABASE
# -----------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME"),
        "USER": config("DB_USER"),
        "PASSWORD": config("DB_PASSWORD"),
        "HOST": config("DB_HOST"),
        "PORT": config("DB_PORT"),
    }
}
# -----------------------------------------------------------------------------
# PASSWORD HASHERS
# -----------------------------------------------------------------------------
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME":
            "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {
        "NAME":
            "django.contrib.auth.password_validation.MinimumLengthValidator"
    },
    {
        "NAME":
            "django.contrib.auth.password_validation.CommonPasswordValidator"
    },
    {
        "NAME":
            "django.contrib.auth.password_validation.NumericPasswordValidator"
    },
]
# -----------------------------------------------------------------------------
# INTERNATIONALIZATION
# -----------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True
# -----------------------------------------------------------------------------
# STATIC FILES
# -----------------------------------------------------------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = (
    "whitenoise.storage.CompressedManifestStaticFilesStorage"
)
# -----------------------------------------------------------------------------
# MEDIA
# -----------------------------------------------------------------------------
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
GIT_REPOSITORY_ROOT = BASE_DIR / "repositories"
GIT_EXECUTABLE = config("GIT_EXECUTABLE", default="git")
DATA_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024
# -----------------------------------------------------------------------------
# DEFAULT PRIMARY KEY
# -----------------------------------------------------------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
# -----------------------------------------------------------------------------
# CUSTOM USER
# -----------------------------------------------------------------------------
# AUTH_USER_MODEL = "accounts.User"
# -----------------------------------------------------------------------------
# DJANGO REST FRAMEWORK
# -----------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_SCHEMA_CLASS":
        "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS":
        "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 10,
}
# -----------------------------------------------------------------------------
# JWT
# -----------------------------------------------------------------------------
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
}
# -----------------------------------------------------------------------------
# SWAGGER
# -----------------------------------------------------------------------------
SPECTACULAR_SETTINGS = {
    "TITLE": "MyProjects API",
    "DESCRIPTION": "Developer Ecosystem API",
    "VERSION": "1.0.0",
}
# -----------------------------------------------------------------------------
# CORS
# -----------------------------------------------------------------------------
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True
# -----------------------------------------------------------------------------
# CSRF
# -----------------------------------------------------------------------------
CSRF_TRUSTED_ORIGINS = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]
# -----------------------------------------------------------------------------
# SECURITY
# -----------------------------------------------------------------------------
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
LOGIN_URL = "/#signin"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/"
X_FRAME_OPTIONS = "DENY"
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
# -----------------------------------------------------------------------------
# EMAIL
# -----------------------------------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
# -----------------------------------------------------------------------------
# LOGGING
# -----------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}
