import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from scholar.jobs import run_next_job


class Command(BaseCommand):
    help = 'Run the persistent paper/Supervisor queue (one process is sufficient).'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **options):
        while True:
            close_old_connections()
            worked = run_next_job()
            if options['once']:
                return
            if not worked:
                time.sleep(1)
