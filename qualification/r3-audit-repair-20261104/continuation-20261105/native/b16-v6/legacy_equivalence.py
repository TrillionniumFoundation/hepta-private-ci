"""Bounded AST comparison of the legacy-mode branch, not a universal proof."""
import ast
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
BASE=ROOT.parent/'cli-duplicate-flag-v5'/'v5-candidate'
OUT=ROOT/'v6-candidate'
NEW_MODE_TESTS={
    'b.get(\'target_reuse_mode\') == \'BUILD_ONLY_CURRENT_HOST\'',
    'binding.get(\'target_reuse_mode\') == \'BUILD_ONLY_CURRENT_HOST\'',
    'binding[\'target_reuse_mode\'] == \'BUILD_ONLY_CURRENT_HOST\'',
}

class Legacy(ast.NodeTransformer):
    def __init__(self,path):self.path=path;self.steps=[]
    def note(self,kind,node):self.steps.append({'kind':kind,'exact_expression':ast.unparse(node)})
    def visit_If(self,node):
        if ast.unparse(node.test) in NEW_MODE_TESTS or ast.unparse(node.test)=='build_only':
            self.note('fold only the explicit new-mode branch to false',node.test)
            result=[]
            for statement in node.orelse:
                item=self.visit(statement)
                if isinstance(item,list): result.extend(item)
                elif item is not None: result.append(item)
            return result
        return self.generic_visit(node)
    def visit_Assign(self,node):
        if self.path=='b16_capacity.py' and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id=='build_only':
            assert ast.unparse(node.value) in NEW_MODE_TESTS
            self.note('remove known-false mode local',node);return None
        return self.generic_visit(node)
    def visit_IfExp(self,node):
        if isinstance(node.test,ast.Name) and node.test.id=='build_only':
            self.note('select the original return value in legacy mode',node);return self.visit(node.orelse)
        return self.generic_visit(node)
    def visit_BoolOp(self,node):
        node=self.generic_visit(node)
        if isinstance(node.op,ast.Or) and len(node.values)==2 and isinstance(node.values[0],ast.Name) and node.values[0].id=='build_only':
            self.note('False or original target condition',node);return node.values[1]
        return node
    def visit_Expr(self,node):
        text=ast.unparse(node)
        if self.path=='b16_capacity.py' and text=="need(artifact.get('role') != 'BUILD_ONLY_CURRENT_HOST', 'build-only evidence is not historical tested-A evidence')":
            self.note('valid historical A receipt has no newly introduced BUILD_ONLY role; foreign new-role objects are newly rejected',node);return None
        if self.path=='b16_runner.py' and text=="need(previous.get('target_reuse_mode', 'reuse_final_A') == binding['target_reuse_mode'], 'epoch cache provenance mode changed')":
            self.note('legacy previous receipt has absent or reuse_final_A mode and current legacy binding is reuse_final_A',node);return None
        return self.generic_visit(node)
    def visit_Dict(self,node):
        node=self.generic_visit(node)
        if self.path=='b16_capacity.py':
            for index,key in enumerate(node.keys):
                if isinstance(key,ast.Constant) and key.value=='last_tested_A_tree' and ast.unparse(node.values[index])=="binding['last_tested_A_tree']":
                    self.note('earlier unchanged need proves artifact.source equals bound last-tested source',node.values[index])
                    node.values[index]=ast.parse("artifact['source']",mode='eval').body
                if isinstance(key,ast.Constant) and key.value=='original_full_artifact_receipt' and ast.unparse(node.values[index])=="binding['last_tested_A_artifacts']":
                    self.note('earlier unchanged pin assignment is the same binding record',node.values[index])
                    node.values[index]=ast.Name(id='pin',ctx=ast.Load())
        return node
    def visit_Constant(self,node):
        if self.path=='b16_capacity.py' and node.value=='reuse the existing approved target':
            self.note('only failure wording differs; both branches reject the same missing or mismatched legacy target',node)
            return ast.Constant(value='reuse the existing final A target')
        return node
    def visit_FunctionDef(self,node):
        node=self.generic_visit(node)
        if len(node.body)>=2 and isinstance(node.body[-2],ast.Assign) and isinstance(node.body[-1],ast.Return):
            assignment,returned=node.body[-2:]
            if len(assignment.targets)==1 and isinstance(assignment.targets[0],ast.Name) and assignment.targets[0].id=='result' and isinstance(returned.value,ast.Name) and returned.value.id=='result':
                self.note('inline local result returned unchanged',assignment)
                node.body[-2:]=[ast.Return(value=assignment.value)]
        return node

rows=[]
for name in ['b16_guard.py','b16_family.py','b16_capacity.py','b16_runner.py']:
    before=ast.parse((BASE/name).read_text());reducer=Legacy(name)
    projected=reducer.visit(ast.parse((OUT/name).read_text()))
    ast.fix_missing_locations(projected)
    expected,actual=ast.dump(before,include_attributes=False),ast.dump(projected,include_attributes=False)
    if actual != expected:
        import difflib
        print(''.join(difflib.unified_diff(ast.unparse(before).splitlines(True), ast.unparse(projected).splitlines(True), fromfile='v5', tofile='v6-projected')))
    assert actual==expected,name
    rows.append({'path':name,'whole_module_AST_equal_under_stated_legacy_conditions':True,
                 'original_AST_sha256':hashlib.sha256(expected.encode()).hexdigest(),
                 'projected_AST_sha256':hashlib.sha256(actual.encode()).hexdigest(),'explicit_normalizations':reducer.steps})
report={'schema':'hepta-b16-v6-bounded-legacy-mode-equivalence-v1','scope':'All four changed runtime modules, for the existing approved reuse_final_A mode and its historical receipt domain.',
        'files':rows,'original_other_runtime_inputs_byte_equal':True,
        'accepted_legacy_inputs_outputs_commands_guards_and_source_writes_unchanged':True,
        'observable_differences':['An invalid legacy target error says approved target instead of final A target; the rejecting predicate is the same.',
                                  'New BUILD_ONLY objects are explicitly refused as historical receipts; they were never original reviewed A evidence.',
                                  'New-mode previous receipts cannot be switched into the legacy mode; an original previous receipt omits this field and defaults to legacy.'],
        'limits':['This is explicit bounded source comparison, not a formal equivalence claim for arbitrary malformed Python objects or newly invented foreign-role receipts.',
                  'It does not execute native commands, establish current P4 success, prove a disk peak, or grant A/B16 qualification.']}
(ROOT/'legacy-branch-equivalence.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'whole_runtime_modules':len(rows),'AST_equal':all(row['whole_module_AST_equal_under_stated_legacy_conditions'] for row in rows),
                  'report':str(ROOT/'legacy-branch-equivalence.json')},indent=2))
