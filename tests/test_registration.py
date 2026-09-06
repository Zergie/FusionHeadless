from __future__ import annotations

import unittest
from unittest.mock import patch

from adapter import FusionAdapter
from context import DefinitionRegistry


class AdapterRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.registry = DefinitionRegistry()
        self.adapter = FusionAdapter()
        patcher = patch("adapter.registry", self.registry)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_registers_existing_functions_and_classes_after_reset(self):
        for target in ("fusion", "server"):
            with self.subTest(target=target):
                def operation():
                    return "registered"

                class Exported:
                    pass

                self.registry.add(operation, target)
                self.registry.add(Exported, target)
                self.registry.reset()
                getattr(self.adapter, f"register_{target}")(operation, Exported)

                definitions = getattr(self.registry, target)
                for value in (operation, Exported):
                    self.assertIs(definitions[value.__name__].value, value)
                    self.assertEqual(definitions[value.__name__].target, target)
                    self.assertEqual(value.__fusionheadless_context__, target)

    def test_rejects_undecorated_and_wrong_process_exports(self):
        for target, other in (("fusion", "server"), ("server", "fusion")):
            for decorated in (False, True):
                with self.subTest(target=target, decorated=decorated):
                    def operation():
                        pass

                    if decorated:
                        self.registry.add(operation, other)
                    with self.assertRaisesRegex(ValueError, f"only @context.{target}"):
                        getattr(self.adapter, f"register_{target}")(operation)
                    self.assertNotIn("operation", getattr(self.registry, target))
                    self.assertEqual(
                        getattr(operation, "__fusionheadless_context__", None),
                        other if decorated else None,
                    )
                    self.registry.reset()
