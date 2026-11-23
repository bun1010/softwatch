# Softwatch

Finds software at an inflection point before it goes mainstream. It ranks by switching
(third parties building on a project) rather than attention, and it never invents a number.

- Design: [docs/PLAN.md](docs/PLAN.md) (read the Revision 3 block first).
- Daily collection runs in GitHub Actions (`.github/workflows/`). Claude scheduled tasks post
  `out/notify.txt` into the Softwatch thread, and the Claude app delivers it to the phone.
- Run locally: `pip install -r requirements.txt && python -m pytest && python -m softwatch daily --dry-run`
- Tests use fixtures and synthetic clients. No test touches the network.
