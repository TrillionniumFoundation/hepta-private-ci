import sys
import unittest
sys.path.insert(0,'/workspace/scratch/7b9383ad4cb1/hepta-private-ci/tools/hepta-engineering-control')
def tests(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from tests(test)
        else:
            yield test
if __name__ == '__main__':
    suite=unittest.defaultTestLoader.discover('/workspace/scratch/7b9383ad4cb1/hepta-private-ci/tools/hepta-engineering-control', pattern='test_*.py')
    unsupported={'test_owned_service','test_counter_task','test_counter_retention'}
    selected=[]
    excluded=[]
    for test in tests(suite):
        (excluded if test.id().split('.')[0] in unsupported else selected).append(test)
    print('Selected',len(selected),'Excluded unprivileged profile tests',len(excluded),flush=True)
    result=unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(selected))
    sys.exit(not result.wasSuccessful())
