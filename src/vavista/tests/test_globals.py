
#  Have to set up real test - just hacking the vista data here

import unittest

from vavista.M import Globals

class TestGlobals(unittest.TestCase):

    def setUp(self):
        g = Globals()
        g["^TESTPGLOBALS"][0][0].value = "TEST"
        g["TESTGLOBALS"][0][0].value = "TMP TEST"

    def tearDown(self):
        g = Globals()
        g["TESTGLOBALS"].kill()
        g["^TESTPGLOBALS"].kill()

    def test_keys(self):
        g = Globals()
        keys = g.keys()
        self.assertEqual("^TESTPGLOBALS" in keys, 1)
        self.assertEqual("TESTGLOBALS" in keys, 0)

        keys = g.keys(include_tmp=True)
        self.assertEqual("^TESTPGLOBALS" in keys, 1)
        self.assertEqual("TESTGLOBALS" in keys, 1)

    def test_serialise(self):
        g = Globals()
        import pdb; pdb.set_trace()
        source = g["^DIC"]["999900"]
        ser = source.serialise(1)
        # TODO: deserialise and compare
        dest = g["MYDIC"]
        dest.deserialise(ser)
        print dest
        
        ser2 = dest.serialise(0)
        dest.kill()
        print dest
        g.deserialise(ser2)
        dest.deserialise(ser)
        print dest



    def test_value(self):
        g = Globals()
        v = g["^TESTPGLOBALS"][0][0].value
        self.assertEqual(v, 'TEST')
        v = g["TESTGLOBALS"][0][0].value
        self.assertEqual(v, 'TMP TEST')

    def test_has_value(self):
        g = Globals()
        v = g["^TESTPGLOBALS"][0][0].has_value()
        self.assertEqual(v, 1)
        v = g["^TESTPGLOBALS"][0].has_value()
        self.assertEqual(v, 0)

    def test_has_decendants(self):
        g = Globals()
        v = g["^TESTPGLOBALS"][0][0].has_decendants()
        self.assertEqual(v, 0)
        v = g["^TESTPGLOBALS"][0].has_decendants()
        self.assertEqual(v, 1)

    def test_subkeys(self):
        g = Globals()
        v = g["^TESTPGLOBALS"]
        keys = v.keys()
        self.assertEqual(len(keys), 0)
        keys = v.keys_with_decendants()
        self.assertEqual(len(keys), 1)

        v = g["^TESTPGLOBALS"][0]
        keys = v.keys()
        self.assertEqual(len(keys), 1)
        keys = v.keys_with_decendants()
        self.assertEqual(len(keys), 0)

    def test_items(self):
        g = Globals()
        v = g["^TESTPGLOBALS"][0]
        items = v.items()
        self.assertEqual(items[0][0], "0")
        self.assertEqual(items[0][1], "TEST")

test_cases = (TestGlobals,)

def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for test_class in test_cases:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)
    return suite
