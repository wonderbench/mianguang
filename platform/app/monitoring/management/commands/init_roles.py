from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "创建本部署的管理员和查看员两种角色。"

    def handle(self, *args, **options):
        admin, _ = Group.objects.get_or_create(name="平台管理员")
        viewer, _ = Group.objects.get_or_create(name="查看员")
        admin.permissions.set(Permission.objects.filter(content_type__app_label__in=["monitoring", "auth"]))
        viewer.permissions.set(Permission.objects.filter(content_type__app_label="monitoring", codename="view_dashboard"))
        self.stdout.write("角色已就绪：平台管理员 / 查看员")
