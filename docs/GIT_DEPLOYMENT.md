# MyProgress Code deployment

MyProgress invokes Git as a separate operating-system process. Keep this boundary intact:

1. Install Git using the deployment operating system's package manager or a separately documented installation layer.
2. Set `GIT_EXECUTABLE` to the Git executable name or absolute path.
3. Do not copy Git source into the Django application or link MyProgress against internal Git libraries.
4. Do not modify or redistribute Git without completing the applicable GPLv2 obligations.
5. If Git is included in a container or installer, include its license notices and corresponding-source information.
6. Use MyProgress branding for the hosting service. Refer to repositories as “Git-compatible” only to explain interoperability.

The following user workflow remains supported:

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://your-domain.example/git/USER_ID/REPOSITORY.git
git push -u origin main
```

Clone remains standard:

```bash
git clone https://your-domain.example/git/USER_ID/REPOSITORY.git
```

The application communicates with Git through command-line arguments and CGI-compatible Smart HTTP input/output. It does not import Git code into the Python process.
