from datetime import timedelta

from django.contrib.admin.models import LogEntry
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from monitoring.models import AuditEntry, Binding, Observation


class Command(BaseCommand):
    help = "清理7天观测、过期绑定身份文本、90天审计/管理日志与过期会话。"

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(70431001)")
            if not cursor.fetchone()[0]:
                raise CommandError("已有清理进程运行。")
        try:
            now = timezone.now()
            cutoff = now - timedelta(days=7)
            deleted = 0
            while ids := list(Observation.objects.filter(received_at__lt=cutoff).order_by("pk").values_list("pk", flat=True)[:5000]):
                deleted += Observation.objects.filter(pk__in=ids).delete()[1].get("monitoring.Observation", 0)
            cleared = Binding.objects.filter(ended_at__lt=cutoff, observations__isnull=True).exclude(
                resident_alias="", location_label_snapshot="").update(resident_alias="", location_label_snapshot="")
            audit_count = AuditEntry.objects.filter(at__lt=now - timedelta(days=90)).delete()[0]
            log_count = LogEntry.objects.filter(action_time__lt=now - timedelta(days=90)).delete()[0]
            sessions = Session.objects.filter(expire_date__lt=now).delete()[0]
            self.stdout.write(f"observations={deleted} bindings_redacted={cleared} audits={audit_count} admin_logs={log_count} sessions={sessions}")
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(70431001)")
