from __future__ import annotations

import json
from datetime import timedelta as td

from django.utils.timezone import now

from hc.api.models import Channel, Check, Notification, Ping
from hc.test import BaseTestCase


class LogTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.check = Check.objects.create(project=self.project)
        self.check.created = "2000-01-01T00:00:00+00:00"
        self.check.save()

        self.ping = Ping.objects.create(owner=self.check, n=1)
        self.ping.body_raw = b"hello world"

        # Older MySQL versions don't store microseconds. This makes sure
        # the ping is older than any notifications we may create later:
        self.ping.created = "2000-01-01T00:00:00+00:00"
        self.ping.save()

        self.url = f"/checks/{self.check.code}/log_events/?success=on&notification=on"

    def test_it_works(self) -> None:
        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(self.url)
        self.assertContains(r, "hello world")

    def test_team_access_works(self) -> None:
        # Logging in as bob, not alice. Bob has team access so this
        # should work.
        self.client.login(username="bob@example.org", password="password")
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)

    def test_it_handles_bad_uuid(self) -> None:
        url = "/checks/not-uuid/log_events/"

        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(url)
        self.assertEqual(r.status_code, 404)

    def test_it_handles_missing_uuid(self) -> None:
        # Valid UUID but there is no check for it:
        url = "/checks/6837d6ec-fc08-4da5-a67f-08a9ed1ccf62/log_events/"

        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(url)
        self.assertEqual(r.status_code, 404)

    def test_it_checks_ownership(self) -> None:
        self.client.login(username="charlie@example.org", password="password")
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 404)

    def test_it_accepts_start_parameter(self) -> None:
        ts = str(now().timestamp())
        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(self.url + "&u=" + ts)
        self.assertNotContains(r, "hello world")

    def test_it_rejects_bad_u_parameter(self) -> None:
        self.client.login(username="alice@example.org", password="password")

        for sample in ["surprise", "100000000000000000"]:
            r = self.client.get(self.url + "&u=" + sample)
            self.assertEqual(r.status_code, 400)

    def test_it_does_not_show_too_old_notifications(self) -> None:
        ch = Channel(kind="email", project=self.project)
        ch.value = json.dumps({"value": "alice@example.org", "up": True, "down": True})
        ch.save()

        n = Notification(owner=self.check)
        n.created = now() - td(hours=1)
        n.channel = ch
        n.check_status = "down"
        n.save()

        Ping.objects.create(owner=self.check, n=101)
        # This makes the ping #1 invisible
        self.check.n_pings = 101
        self.check.save()

        self.client.login(username="alice@example.org", password="password")
        r = self.client.get(self.url)

        # The notification should not show up in the log as it is
        # older than the oldest visible ping:
        self.assertNotContains(r, "Sent email to alice@example.org", status_code=200)
