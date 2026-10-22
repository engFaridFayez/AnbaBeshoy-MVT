import base64
import hashlib
import re
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.crypto import salted_hmac


def session_tag(request):
    key = request.session.session_key or ""
    return salted_hmac("notices.device.session", key).hexdigest()


def validate_endpoint(endpoint):
    if not isinstance(endpoint, str) or len(endpoint) > 2048:
        raise ValidationError("عنوان خدمة الإشعارات غير صالح.")
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError:
        raise ValidationError("عنوان خدمة الإشعارات غير صالح.")
    allowed = getattr(settings, "NOTIFICATION_PUSH_HOSTS", (
        "fcm.googleapis.com",
        "updates.push.services.mozilla.com",
        "web.push.apple.com",
    ))
    # Exact public-provider allowlist; never allow arbitrary user-supplied URLs.
    if (
        parsed.scheme != "https" or parsed.hostname not in allowed
        or port not in (None, 443) or parsed.username or parsed.password
        or parsed.fragment or not parsed.path.startswith("/")
        or any(char.isspace() for char in endpoint)
    ):
        raise ValidationError("خدمة Push غير مدعومة أو عنوانها غير آمن.")
    return endpoint


def decode_key(value, size):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", value):
        raise ValidationError("مفاتيح الاشتراك غير صالحة.")
    try:
        data = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, TypeError):
        raise ValidationError("مفاتيح الاشتراك غير صالحة.")
    if len(data) != size:
        raise ValidationError("مفاتيح الاشتراك غير صالحة.")
    return data


def validate_subscription(data):
    if not isinstance(data, dict):
        raise ValidationError("بيانات الاشتراك غير صالحة.")
    endpoint = validate_endpoint(data.get("endpoint"))
    keys = data.get("keys")
    if not isinstance(keys, dict):
        raise ValidationError("مفاتيح الاشتراك غير صالحة.")
    public = decode_key(keys.get("p256dh"), 65)
    decode_key(keys.get("auth"), 16)
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public)
    except (ValueError, TypeError):
        raise ValidationError("مفتاح الجهاز غير صالح.")
    return {
        "endpoint": endpoint,
        "endpoint_hash": hashlib.sha256(endpoint.encode()).hexdigest(),
        "p256dh": keys["p256dh"],
        "auth": keys["auth"],
    }
