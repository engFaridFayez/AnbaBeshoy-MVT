import logging

from django.contrib.auth.signals import user_logged_out
from django.db import DatabaseError, transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import PushSubscription
from .services import observe_menu

logger = logging.getLogger(__name__)


@receiver(post_save, sender="kitchen.DailyMenu", dispatch_uid="notices_menu_saved")
def menu_saved(sender, instance, raw=False, using="default", **kwargs):
    if raw or using != "default":
        return

    def after_commit():
        try:
            observe_menu(instance.pk)
        except DatabaseError:
            # Also permits migration/startup before notification tables exist.
            # The worker reconciles the committed state on its next iteration.
            logger.warning("Menu notification deferred to worker: menu=%s", instance.pk)

    transaction.on_commit(after_commit, using=using)


@receiver(user_logged_out, dispatch_uid="notices_logout")
def detach_logged_out_device(sender, request, user, **kwargs):
    if not request or not user:
        return
    from .security import session_tag
    try:
        PushSubscription.objects.filter(
            user=user, session_tag=session_tag(request),
        ).update(active=False)
    except DatabaseError:
        logger.warning("Push subscriptions could not be detached on logout.")
