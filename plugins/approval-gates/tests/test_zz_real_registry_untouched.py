"""A full run of this folder's tests leaves the real registry folder of AI-DLC artifact links as it was.
Named so that it runs last: the listing it compares with is taken when the suite is loaded, before any test runs."""

import os
import unittest

import registry_isolation as iso

BEFORE = iso.real_listing()


class TestRealRegistryUntouched(unittest.TestCase):
    def test_the_registry_is_a_temporary_folder(self):
        self.assertEqual(os.environ["AIDLC_ARTIFACTS_DIR"], iso.TEMP)
        self.assertNotEqual(os.path.realpath(iso.TEMP), os.path.realpath(iso.REAL))

    def test_the_real_registry_folder_is_as_it_was_before_the_run(self):
        self.assertEqual(iso.real_listing(), BEFORE)


if __name__ == "__main__":
    unittest.main()
