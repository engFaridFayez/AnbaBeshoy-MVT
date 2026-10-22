import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from kitchen.models import DailyMenu, DailyMenuItem, MenuItem
from .forms import ComposeForm
from .models import MenuAudience, MenuState, Notice, PushSubscription, Receipt
from .security import validate_endpoint
from .services import create_notice, current_menu_url, observe_menu, reconcile_menus
from .views import issue_token


@override_settings(NOTIFICATIONS_PUSH_ENABLED=False)
class NotificationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.monk = User.objects.create_user(
            username="notification_test_monk", password="Test-password-43!", role="monk",
        )
        self.other = User.objects.create_user(
            username="notification_test_other", password="Test-password-43!", role="monk",
        )
        self.manager = User.objects.create_user(
            username="notification_test_admin", password="Test-password-43!", role="admin",
        )
        self.menu = DailyMenu.objects.create(
            date=timezone.localdate(), meal_type="breakfast", is_published=False,
        )
        self.item = MenuItem.objects.create(name="Test beans", category="food", is_active=True)
        DailyMenuItem.objects.create(daily_menu=self.menu, item=self.item, is_available=True)
        observe_menu(self.menu.pk, baseline=True)

    def open_menu(self):
        self.menu.is_published = True
        self.menu.save()
        observe_menu(self.menu.pk)

    def notice(self, key="manual:test"):
        return create_notice(
            title="Test", body="Message", kind=Notice.Kind.MANUAL,
            recipients=get_user_model().objects.filter(pk=self.monk.pk),
            dedupe_key=key, actor=self.manager,
        )[0]

    def test_open_notifies_all_active(self):
        self.open_menu()
        self.assertEqual(Notice.objects.count(), 1)
        self.assertEqual(Receipt.objects.count(), 3)

    def test_same_open_state_does_not_duplicate(self):
        self.open_menu()
        observe_menu(self.menu.pk)
        self.assertEqual(Notice.objects.count(), 1)

    def test_close_then_reopen_are_new_events(self):
        self.open_menu()
        self.menu.is_published = False
        self.menu.save()
        observe_menu(self.menu.pk)
        self.menu.is_published = True
        self.menu.save()
        observe_menu(self.menu.pk)
        self.assertEqual(Notice.objects.count(), 3)

    def test_selected_audience_is_respected(self):
        policy = MenuAudience.objects.create(menu=self.menu, mode="selected")
        policy.users.add(self.monk)
        self.open_menu()
        self.assertEqual(list(Receipt.objects.values_list("user_id", flat=True)), [self.monk.pk])

    def test_empty_selected_audience_does_not_become_all(self):
        MenuAudience.objects.create(menu=self.menu, mode="selected")
        self.open_menu()
        self.assertFalse(Receipt.objects.exists())

    def test_disabled_automatic_audience(self):
        MenuAudience.objects.create(menu=self.menu, enabled=False)
        self.open_menu()
        self.assertFalse(Receipt.objects.exists())

    def test_inactive_user_is_excluded(self):
        self.other.is_active = False
        self.other.save()
        self.open_menu()
        self.assertEqual(Receipt.objects.count(), 2)

    def test_deadline_emits_close_once(self):
        self.open_menu()
        self.menu.ordering_deadline = timezone.now() - timedelta(seconds=1)
        self.menu.save()
        reconcile_menus()
        reconcile_menus()
        self.assertEqual(Notice.objects.filter(kind=Notice.Kind.CLOSE).count(), 1)

    def test_queryset_update_is_reconciled(self):
        DailyMenu.objects.filter(pk=self.menu.pk).update(is_published=True)
        reconcile_menus()
        self.assertEqual(Notice.objects.count(), 1)

    def test_baseline_does_not_broadcast_existing_open_menus(self):
        other_menu = DailyMenu.objects.create(
            date=timezone.localdate(), meal_type="lunch", is_published=True,
        )
        DailyMenuItem.objects.create(daily_menu=other_menu, item=self.item, is_available=True)
        observe_menu(other_menu.pk, baseline=True)
        observe_menu(other_menu.pk)
        self.assertFalse(Notice.objects.exists())

    def test_signal_runs_after_commit(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.menu.is_published = True
            self.menu.save()
        self.assertEqual(Notice.objects.count(), 1)

    def test_transaction_rollback_does_not_send(self):
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    self.menu.is_published = True
                    self.menu.save()
                    raise ValueError("rollback")
            except ValueError:
                pass
        self.assertFalse(Notice.objects.exists())

    def test_manual_dedupe(self):
        self.notice()
        self.notice()
        self.assertEqual(Notice.objects.count(), 1)
        self.assertEqual(Receipt.objects.count(), 1)

    def test_each_user_sees_only_their_receipts(self):
        self.notice()
        self.client.force_login(self.other)
        data = self.client.get(reverse("notifications:feed")).json()
        self.assertEqual(data["unread"], 0)
        self.assertEqual(data["items"], [])

    def test_read_other_users_notification_is_forbidden(self):
        notice = self.notice()
        receipt = notice.receipts.get()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("notifications:detail", args=[receipt.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("notifications:read", args=[receipt.pk])).status_code, 404)

    def test_read_post_is_idempotent(self):
        receipt = self.notice().receipts.get()
        self.client.force_login(self.monk)
        url = reverse("notifications:read", args=[receipt.pk])
        self.client.post(url)
        receipt.refresh_from_db()
        first = receipt.read_at
        self.client.post(url)
        receipt.refresh_from_db()
        self.assertEqual(receipt.read_at, first)

    def test_read_all_only_current_user(self):
        self.open_menu()
        self.client.force_login(self.monk)
        self.client.post(reverse("notifications:read_all"))
        self.assertEqual(Receipt.objects.filter(read_at__isnull=False).count(), 1)

    def test_regular_monk_cannot_manage(self):
        self.client.force_login(self.monk)
        self.assertEqual(self.client.get(reverse("notifications:manage")).status_code, 403)
        self.assertEqual(self.client.post(reverse("notifications:manage")).status_code, 403)

    def test_anonymous_api_gets_401(self):
        self.assertEqual(self.client.get(reverse("notifications:feed")).status_code, 401)

    def test_manual_manager_form(self):
        self.client.force_login(self.manager)
        data = {
            "action": "send", "send-title": "Manual title", "send-body": "Manual body",
            "send-mode": "selected", "send-users": [str(self.monk.pk)],
            "send-token": issue_token(self.manager), "send-menu": "",
        }
        response = self.client.post(reverse("notifications:manage"), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Receipt.objects.count(), 1)
        self.client.post(reverse("notifications:manage"), data)
        self.assertEqual(Receipt.objects.count(), 1)

    def test_selection_requires_at_least_one_user(self):
        form = ComposeForm(data={
            "title": "Title", "body": "Body", "mode": "selected",
            "token": issue_token(self.manager),
        })
        self.assertFalse(form.is_valid())
        self.assertIn("users", form.errors)

    def test_old_and_future_notices_do_not_open_today_menu(self):
        note = self.notice()
        note.menu = self.menu
        note.meal_type = "breakfast"
        note.menu_date = timezone.localdate() - timedelta(days=1)
        self.assertIsNone(current_menu_url(note))
        note.menu_date = timezone.localdate() + timedelta(days=1)
        self.assertIsNone(current_menu_url(note))
        note.menu_date = timezone.localdate()
        self.assertIn("meal=breakfast", current_menu_url(note))

    def test_endpoint_validation_blocks_private_and_unlisted_hosts(self):
        from django.core.exceptions import ValidationError
        for url in ("http://localhost/a", "https://127.0.0.1/a", "https://example.com/a",
                    "https://fcm.googleapis.com.evil.example/a",
                    "https://fcm.googleapis.com:8443/a", "https://u:p@fcm.googleapis.com/a"):
            with self.assertRaises(ValidationError):
                validate_endpoint(url)
        self.assertEqual(
            validate_endpoint("https://fcm.googleapis.com/fcm/send/test"),
            "https://fcm.googleapis.com/fcm/send/test",
        )

    def test_private_key_is_not_exposed_by_config(self):
        self.client.force_login(self.monk)
        with patch("notifications.views.push_config", return_value={
            "public_key": "public", "private_key": "secret", "subject": "mailto:x@example.org",
        }):
            response = self.client.get(reverse("notifications:config"))
        self.assertNotIn("secret", response.content.decode())
        self.assertNotIn("private_key", response.json())

    def test_get_cannot_mark_read(self):
        receipt = self.notice().receipts.get()
        self.client.force_login(self.monk)
        self.assertEqual(self.client.get(reverse("notifications:read", args=[receipt.pk])).status_code, 405)

    def test_worker_has_no_cache_and_root_scope_header(self):
        response = self.client.get(reverse("notifications_worker"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Service-Worker-Allowed"], "/")
        self.assertIn("no-store", response["Cache-Control"])

    def test_csrf_enforced_for_mark_read(self):
        from django.test import Client
        receipt = self.notice().receipts.get()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.monk)
        response = client.post(reverse("notifications:read", args=[receipt.pk]))
        self.assertEqual(response.status_code, 403)

    def test_empty_published_menu_does_not_announce_open(self):
        self.menu.entries.update(is_available=False)
        self.open_menu()
        self.assertFalse(Notice.objects.filter(kind=Notice.Kind.OPEN).exists())

    def test_disabling_last_item_closes_effective_menu(self):
        self.open_menu()
        self.menu.entries.update(is_available=False)
        reconcile_menus()
        self.assertEqual(Notice.objects.filter(kind=Notice.Kind.CLOSE).count(), 1)
