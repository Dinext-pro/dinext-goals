# GitHub validation

Checks run on pull requests and maintained branches using the public Dinext validation support, or the private owning repository for Docs and Control Center. App unit tests use a disposable bench with local MariaDB and Redis. CI receives no production credentials.

Imported upstream workflows are retained under `imported-workflows-disabled` for review. Deployment, publishing, live production smoke checks, paid agents and external notifications remain disabled. The private migration archive retains source settings and CI records.

For app tests, the Actions log records the source and support revisions. The portable select-control wheel retains its existing package checks; CRM retains its frontend unit tests.
