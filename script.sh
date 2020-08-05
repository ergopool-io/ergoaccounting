#!/bin/bash
coverage run --omit="*/migrations/*","*/wsgi.py","*/urls.py","*/settings.py","*/production.py" --source=core,ErgoAccounting manage.py test -v 2
coverage report --fail-under=85