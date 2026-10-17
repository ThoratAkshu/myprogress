from pathlib import Path
from decouple import config
from datetime import timedelta
def env_list(name, default=""):
    return [item.strip() for item in config(name, default=default).split(",") if item.strip()]
# -----------------------------------------------------------------------------
# PATHS
# -----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent
# -----------------------------------------------------------------------------
# CORE SETTINGS
# -----------------------------------------------------------------------------
SECRET_KEY = config("SECRET_KEY")
DEBUG = str(config("DEBUG", default="false")).strip().lower() in {"1", "true", "yes", "on", "debug"}
# Comma-separated, e.g. "myprogress.dev,www.myprogress.dev". When empty and DEBUG is on, Django allows localhost only.
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS")
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
    "apps.recruiting",
    "apps.learning",
    "apps.code",
    "apps.earnings",
    "apps.organizations",
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
    "apps.accounts.middleware.RoleAccessMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.organizations.middleware.OrganizationAccessMiddleware",
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
                "apps.common.context_processors.workspace_navigation",
                "apps.common.context_processors.ui_theme",
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
# STATICFILES_STORAGE was removed in Django 5.1; storages are configured here.
STORAGES = {
    "default": {"BACKEND": config("MEDIA_STORAGE_BACKEND", default="django.core.files.storage.FileSystemStorage")},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
# -----------------------------------------------------------------------------
# MEDIA
# -----------------------------------------------------------------------------
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(config("MEDIA_ROOT", default=str(BASE_DIR / "media")))
GIT_REPOSITORY_ROOT = Path(config("GIT_REPOSITORY_ROOT", default=str(BASE_DIR / "repositories")))
GIT_EXECUTABLE = config("GIT_EXECUTABLE", default="git")
# Learning studio drafts. Without a key the studio still builds a starter draft from the branch.
ANTHROPIC_API_KEY = config("ANTHROPIC_API_KEY", default="")
AI_MODEL = config("AI_MODEL", default="claude-opus-5-5")
AI_TIMEOUT = config("AI_TIMEOUT", default=90, cast=int)
# Creator payments through RazorpayX Payouts. Leave empty to send payments by hand and record their UTR.
RAZORPAYX_KEY_ID = config("RAZORPAYX_KEY_ID", default="")
RAZORPAYX_KEY_SECRET = config("RAZORPAYX_KEY_SECRET", default="")
RAZORPAYX_ACCOUNT_NUMBER = config("RAZORPAYX_ACCOUNT_NUMBER", default="")
RAZORPAYX_WEBHOOK_SECRET = config("RAZORPAYX_WEBHOOK_SECRET", default="")
# Color theme for the app: ocean, emerald, or midnight.
UI_THEME = config("UI_THEME", default="midnight")
# Git requests are streamed, so form posts no longer need a large in-memory limit.
GIT_MAX_REQUEST_BYTES = config("GIT_MAX_REQUEST_BYTES", default=1024 * 1024 * 1024, cast=int)
GIT_HTTP_TIMEOUT = config("GIT_HTTP_TIMEOUT", default=600, cast=int)
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
# -----------------------------------------------------------------------------
# CACHE (rate limits live here; use Redis when running more than one process)
# -----------------------------------------------------------------------------
REDIS_URL = config("REDIS_URL", default="")
CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}} if REDIS_URL else {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
# Only enable behind a proxy you control that overwrites X-Forwarded-For.
TRUST_X_FORWARDED_FOR = config("TRUST_X_FORWARDED_FOR", default=False, cast=bool)
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
# Only listed origins may make cross-origin requests; empty means none.
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = False
# -----------------------------------------------------------------------------
# CSRF
# -----------------------------------------------------------------------------
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000")
# The site's address, for links in emails sent by scheduled jobs (there's no request to read it from).
SITE_URL = config("SITE_URL", default=(CSRF_TRUSTED_ORIGINS or ["http://localhost:8000"])[0]).rstrip("/")
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
EMAIL_BACKEND = config("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = config("EMAIL_HOST", default="localhost")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="MyProgress <no-reply@localhost>")
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24
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
# -----------------------------------------------------------------------------
# VIDEO CLASSES
# -----------------------------------------------------------------------------
# A Jitsi Meet server to hold live classes inside MyProgress, like meet.yourinstitute.in.
# Empty: classes open a meet.jit.si room in a new tab (meet.jit.si ends embedded calls after 5 minutes).
JITSI_DOMAIN = config("JITSI_DOMAIN", default="").strip().removeprefix("https://").strip("/")
# Set both when that server uses token authentication (the app_id and app_secret from its Prosody config).
JITSI_APP_ID = config("JITSI_APP_ID", default="")
JITSI_APP_SECRET = config("JITSI_APP_SECRET", default="")
