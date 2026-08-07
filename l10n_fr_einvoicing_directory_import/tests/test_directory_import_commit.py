# Copyright 2026 Sudokeys
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import threading
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDirectoryImportCommit(TransactionCase):
    """The per-batch commit of the CSV import must stand down under tests.

    `_directory_import_csv` commits after every batch so the recompute queue
    stays bounded on a loaded database. That is right in production and wrong
    under `TransactionCase`, which relies on rolling the whole test back: a
    real commit persists the fixtures and leaves the following tests facing a
    database that no longer matches their expectations.
    """

    def test_batch_commit_is_skipped_while_testing(self):
        Line = self.env["fr.directory.line"]
        self.assertTrue(
            getattr(threading.current_thread(), "testing", False),
            "the test runner is expected to flag the current thread",
        )
        with patch.object(type(self.env.cr), "commit") as commit:
            Line._directory_commit()
        commit.assert_not_called()

    def test_batch_commit_fires_outside_tests(self):
        Line = self.env["fr.directory.line"]
        thread = threading.current_thread()
        testing = getattr(thread, "testing", False)
        thread.testing = False
        try:
            with patch.object(type(self.env.cr), "commit") as commit:
                Line._directory_commit()
            commit.assert_called_once()
        finally:
            thread.testing = testing
