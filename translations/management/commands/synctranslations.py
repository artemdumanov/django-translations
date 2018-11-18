import sys

from django.core.management.base import (
    BaseCommand, CommandError, no_translations,
)
from django.apps import apps
from django.db.models import Q
from django.contrib.contenttypes.models import ContentType

from translations.models import Translation, Translatable


class NotRunningInTTYException(Exception):
    pass


class Command(BaseCommand):
    help = "Synchronize the translations."

    def add_arguments(self, parser):
        parser.add_argument(
            'app_label',
            nargs='?',
            help='App label of an application to synchronize the state.',
        )
        parser.add_argument(
            '--noinput', '--no-input',
            action='store_false',
            dest='interactive',
            help='Tells Django to NOT prompt the user for input of any kind.',
        )

    def execute(self, *args, **options):
        self.stdin = options.get('stdin', sys.stdin)  # Used for testing
        return super().execute(*args, **options)

    @no_translations
    def handle(self, *args, **options):

        # get arguments
        verbosity = options['verbosity']
        interactive = options['interactive']
        app_label = options['app_label']

        # validate app label and get the models (content types)
        if app_label:
            for app_config in apps.get_app_configs():
                if app_config.label == app_label:
                    break
            else:
                raise CommandError(
                    "App '{}' is not found.".format(app_label)
                )
            content_types = ContentType.objects.filter(app_label=app_label)
        else:
            content_types = ContentType.objects.all()

        # fetch the translations to delete
        query = Q()
        for content_type in content_types:
            model = content_type.model_class()
            if issubclass(model, Translatable):
                translatable_fields = model._get_translatable_fields_names()
                model_query = (
                    Q(content_type=content_type)
                    &
                    ~Q(field__in=translatable_fields)
                )
            else:
                model_query = Q(content_type=content_type)
            query |= model_query
        queryset = Translation.objects.filter(query)

        # synchronize if there's anything to do so
        if queryset:

            # tell user what will be deleted
            if verbosity >= 1:
                changes = {}
                for instance in queryset:
                    model_name = str(instance.content_type.model_class().__name__)
                    changes.setdefault(model_name, set())
                    changes[model_name].add(instance.field)
                change_list = [
                    "- '{}' field{} in '{}' model".format(
                        ', '.join(fields),
                        's' if len(fields) > 1 else '',
                        model,
                    )
                    for model, fields in changes.items()
                ]
                self.stdout.write('The translations for the following will be deleted:')
                self.stdout.write('\n'.join(change_list))

            if interactive:
                run = None
                try:
                    if hasattr(self.stdin, 'isatty') and not self.stdin.isatty():
                        raise NotRunningInTTYException("Not running in a TTY")

                    while run is None:
                        raw_value = input(
                            'Are you sure you want to synchronize '
                            'translations? [Y/n] '
                        ).lower()

                        # default
                        if raw_value == '':
                            raw_value = 'y'

                        # yes or no?
                        if raw_value in ['y', 'yes']:
                            return True
                        elif raw_value in ['n', 'no']:
                            return False
                        else:
                            return None
                except KeyboardInterrupt:
                    self.stderr.write("\nOperation cancelled.")
                    sys.exit(1)
                except NotRunningInTTYException:
                    self.stdout.write(
                        "Synchronizing translations skipped due to not running in a TTY. "
                        "You can run `manage.py synctranslations` in your project "
                        "to synchronize translations manually."
                    )
            else:
                run = True

            if run:
                queryset.delete()
                self.stdout.write(self.style.SUCCESS('Successfully synchronized translations.'))
            else:
                self.stdout.write(self.style.NOTICE('Synchronizing translations cancelled.'))
        else:
            self.stdout.write(self.style.SUCCESS('No translations to synchronize.'))
