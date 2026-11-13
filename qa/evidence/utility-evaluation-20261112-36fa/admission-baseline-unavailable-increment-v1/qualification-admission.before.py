"""Exact-source admission only; original native/source gate drivers remain unchanged.

This module has no CLI and performs no work when imported. It is a HOLD until
Root binds the actual final-format, canonical alignment and runtime proofs.
"""
from pathlib import Path
import ast
import io
import textwrap
import fcntl
import gzip
import hashlib
import json
import os
import re
import stat
import sys
import types

V5_PIN = {'bytes': 63007, 'sha256': 'ff2078884d48dcb92ec3b681d7479c33e9b074d1677108ce60e913c90f002431', 'git_blob': '6632d0cc1e0a127db9ee3324b32bf2d2fc2f7735'}
INVENTORY_PIN = {'bytes': 22946, 'sha256': '20c11034146f6739dd24e9d7e33b94ee909754b07ce6295c242c842c5f3c40b2', 'git_blob': '51181866cbbb6e0176aab04117efffa8b6792b31'}
PLAN_PIN = {'bytes': 32246, 'sha256': '2a2df598aa5b2673b55465c3978cb6c51a22326fde9878d97f39bf984e905619', 'git_blob': '3aefbc71d69d8014eed9e5a18269bbcc866a7583'}
C0F = 'c0f78493f815780f68b9bf5e390a21314d79311f'

HISTORICAL_REPO = '/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1'
DONOR_REPO = '/home/qian-qi/hepta-utility-36fa-native-cc57-isolated-v1'
CURRENT_REPO = '/home/qian-qi/hepta-utility-36fa-provider-coordinator-a489-isolated-v1'
MATERIALIZED_SUBJECT = {'commit': 'd25675445c39f76db69a7bd8e71a1a72e1cd5b9f',
 'parents': ['cc57c7198db6293ccca562253c42fffbe2a04633'],
 'tree': 'a489b394666b8141840275128a780605b024cde0'}
DONOR_SUBJECT = {'commit': 'cc57c7198db6293ccca562253c42fffbe2a04633',
 'parents': ['246d8cb614770252ee42029a5c014f2a4904176a'],
 'tree': 'b7b357c07b5539769a068c6b9b009629f5612d1e'}
FINAL_SUBJECT = {'commit': 'b6084394a4a38ab495c16eaba09e879f04a96f8e',
 'parents': ['d25675445c39f76db69a7bd8e71a1a72e1cd5b9f'],
 'tree': '8ebb37e523ad3932a58cf016af0a9f4e0eeb6638'}
RUNTIME_GUARD = {'create_target_if_absent': False,
 'environment': {'CARGO_BUILD_JOBS': '2',
                 'CARGO_HOME': '/home/qian-qi/.cargo',
                 'CARGO_INCREMENTAL': '0',
                 'CARGO_NET_OFFLINE': 'true',
                 'CARGO_PROFILE_DEV_DEBUG': '0',
                 'CARGO_PROFILE_TEST_DEBUG': '0',
                 'CARGO_TARGET_DIR': '/data/hepta-utility-36fa-final-native-target-v1',
                 'PATH': '/data/hepta-utility-36fa-runtime-materials-86dd-v1/bin:/home/qian-qi/hepta-learn-037c-tools/nextest-0.9.103-e999c122:/home/qian-qi/.cargo/bin:/usr/local/bin:/usr/bin:/bin',
                 'RUFF_CACHE_DIR': '/data/hepta-utility-36fa-runtime-materials-86dd-v1/ruff-cache',
                 'RUSTUP_HOME': '/home/qian-qi/.rustup',
                 'RUSTUP_TOOLCHAIN': '1.96.0',
                 'RUSTY_V8_ARCHIVE': '/data/hepta-utility-36fa-runtime-materials-86dd-v1/v8-150.4.0-gnu-sandbox/librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz',
                 'RUSTY_V8_SRC_BINDING_PATH': '/data/hepta-utility-36fa-runtime-materials-86dd-v1/v8-150.4.0-gnu-sandbox/src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.rs',
                 'UV_CACHE_DIR': '/data/hepta-utility-36fa-runtime-materials-86dd-v1/uv-cache',
                 'UV_OFFLINE': 'true',
                 'UV_PROJECT_ENVIRONMENT': '/data/hepta-utility-36fa-runtime-materials-86dd-v1/scripts-project-environment',
                 'UV_PYTHON_DOWNLOADS': 'never'},
 'formatter_tool_files': {'python': {'bytes': 8020928,
                                     'mode': 493,
                                     'path': '/data/hepta-utility-36fa-runtime-materials-86dd-v1/scripts-project-environment/bin/python',
                                     'resolved': '/usr/bin/python3.12',
                                     'sha256': 'e50d468e8b0adfb05733f5b87b3cff34829c4a8c1aea50c865aa8bdfe4bb150f'},
                          'ruff': {'bytes': 27849024,
                                   'mode': 457,
                                   'path': '/data/hepta-utility-36fa-runtime-materials-86dd-v1/scripts-project-environment/bin/ruff',
                                   'resolved': '/data/hepta-utility-36fa-runtime-materials-86dd-v1/scripts-project-environment/bin/ruff',
                                   'sha256': 'e7fe044c1215edf671c497dc77312d329237f827e50ecfcb7266a662a110dc97'}},
 'inherited_source_environment': {'CODEX_REPO_ROOT': None, 'PYTHONPATH': None},
 'minimum_target_free_bytes': 34359738368,
 'runtime_restoration': {'environment': {'bytes': 21724,
                                         'git_blob': '8b62ac16f554c1f34ee72974637752f5a3b58aec',
                                         'sha256': 'd37a2b3eccf86e42643676d86cf0232ce1931de4693f45bb295761bb42da2172'},
                         'environment_path': '/home/qian-qi/hepta-utility-36fa-evidence/runtime-materials-restore-86dd-v1/run-v2/ENVIRONMENT_READY.json',
                         'job_id': '1a1d0fcb212-2564-1bf4',
                         'result': {'bytes': 21366,
                                    'git_blob': '7832ed48200e8361ae4a7dd5ca8b7b5f7f289b09',
                                    'sha256': '272f2f2719d92b14939273d8807f5d1143b1307b7de78c4499fbfdad10f13a90'},
                         'result_path': '/home/qian-qi/hepta-utility-36fa-evidence/runtime-materials-restore-86dd-v1/run-v2/RESULT.json',
                         'supervisor': {'bytes': 954,
                                        'git_blob': '3705e1ded34c017b57ee9eb13472f67df0da8e20',
                                        'sha256': '6709b0594c9649b28cd1d16651b3181458681296cdd2e5d56cf996f16e8deceb'},
                         'supervisor_path': '/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/RUNTIME_RESTORATION_SUPERVISOR.original.json'},
 'tool_files': {'cargo': {'bytes': 21139856,
                          'mode': 493,
                          'path': '/home/qian-qi/.cargo/bin/cargo',
                          'resolved': '/home/qian-qi/.cargo/bin/rustup',
                          'sha256': '5be191e8c70a5007074254cb74d78dbfdd25cd5a61c27de7b8e5410122ec24f4'},
                'git': {'bytes': 4066232,
                        'mode': 493,
                        'path': '/usr/bin/git',
                        'resolved': '/usr/bin/git',
                        'sha256': 'eb54b535467e0975c1284d4c4d08eea779aeb248a5d34b02e2ee171382e22201'},
                'just': {'bytes': 5347728,
                         'mode': 509,
                         'path': '/home/qian-qi/.cargo/bin/just',
                         'resolved': '/home/qian-qi/.cargo/bin/just',
                         'sha256': 'b73359690704c2aaa0cdfb5b262e6fbf819a8be8cdea2d87565dd441dc7b3f8d'},
                'python3': {'bytes': 8020928,
                            'mode': 493,
                            'path': '/usr/bin/python3',
                            'resolved': '/usr/bin/python3.12',
                            'sha256': 'e50d468e8b0adfb05733f5b87b3cff34829c4a8c1aea50c865aa8bdfe4bb150f'},
                'rustup': {'bytes': 21139856,
                           'mode': 493,
                           'path': '/home/qian-qi/.cargo/bin/rustup',
                           'resolved': '/home/qian-qi/.cargo/bin/rustup',
                           'sha256': '5be191e8c70a5007074254cb74d78dbfdd25cd5a61c27de7b8e5410122ec24f4'},
                'uv': {'bytes': 59258456,
                       'mode': 448,
                       'path': '/data/hepta-utility-36fa-runtime-materials-86dd-v1/bin/uv',
                       'resolved': '/data/hepta-utility-36fa-runtime-materials-86dd-v1/bin/uv',
                       'sha256': 'fa5fc652fa5ed5b44fa8e7dda507f27975c02f59643787fd8ab4bf36f1ba7438'}},
 'tool_identity_projection': ['path', 'resolved', 'bytes', 'sha256', 'mode'],
 'v8_files': {'RUSTY_V8_ARCHIVE': {'bytes': 29366352,
                                   'mode': 384,
                                   'path': '/data/hepta-utility-36fa-runtime-materials-86dd-v1/v8-150.4.0-gnu-sandbox/librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz',
                                   'resolved': '/data/hepta-utility-36fa-runtime-materials-86dd-v1/v8-150.4.0-gnu-sandbox/librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz',
                                   'sha256': 'a35c75d1f26e6a983885a45b33490a4ebe54f05050568b32b89cfb421b30b583'},
              'RUSTY_V8_SRC_BINDING_PATH': {'bytes': 39884,
                                            'mode': 384,
                                            'path': '/data/hepta-utility-36fa-runtime-materials-86dd-v1/v8-150.4.0-gnu-sandbox/src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.rs',
                                            'resolved': '/data/hepta-utility-36fa-runtime-materials-86dd-v1/v8-150.4.0-gnu-sandbox/src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.rs',
                                            'sha256': '7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506'}}}
COORDINATION_LOCK = {'device': 2050,
 'inode': 50139448,
 'mode': 384,
 'nlink': 1,
 'path': '/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/SOURCE_COORDINATION.lock',
 'uid': 1000}
FIXED_INPUTS = {'ARCHIVE_V3_ARTIFACTS': {'path': '/home/qian-qi/hepta-utility-36fa-evidence/v8-single-archive-restore-v3/run/ARTIFACTS.json',
                          'pin': {'bytes': 28169,
                                  'git_blob': '0b206ef6b276e88c0574d58faa88798d9f00158d',
                                  'sha256': '4e08da141f0d5e54614425ad4f3b58a6dabb9dadf934e204d12512b87f45ac8d'}},
 'ARCHIVE_V3_READBACK': {'path': '/home/qian-qi/hepta-utility-36fa-evidence/v8-single-archive-restore-v3/run/ARCHIVE_READBACK.json',
                         'pin': {'bytes': 496,
                                 'git_blob': 'e1c3ebf8a5c1a0de7b3aaa15189bbc1e733266a8',
                                 'sha256': 'd207d1d6fc544ea9eaf3b129b1b0d72f1ed10ee180e7aa6b1f4c6c1bbf884052'}},
 'FINAL_FORMAT_ARTIFACTS': {'path': '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-nonrust-format-v1/run/ARTIFACTS.json',
                            'pin': {'bytes': 67498,
                                    'git_blob': '0119bbc670ec82b93b5235d9e512f61f58baf409',
                                    'sha256': 'abec7769c53d7d87af8deb5e7d71841622c1575e72bd901b63cc46e13d7f515f'}},
 'FINAL_FORMAT_CONFIG': {'path': '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-nonrust-format-v1/APPROVED_CONFIG.json',
                         'pin': {'bytes': 2906,
                                 'git_blob': 'c05c83f1b6ce14afa2bcef5c9e4d8eaae3059708',
                                 'sha256': '9f8bd53789bbcfee921e9fdf41f5fac937fafd58cfad8306f64096e10de723d1'}},
 'FINAL_FORMAT_DRIVER': {'path': '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-nonrust-format-v1/driver.py',
                         'pin': {'bytes': 28657,
                                 'git_blob': '27c0db4e4bceb69bcaafc97f5cc843a37b180941',
                                 'sha256': 'f744383af73475b32fc866298c4e59ebfa70ed5cb5cee7a7837d7770f778ff46'}},
 'HISTORICAL_ENVIRONMENT_READY': {'path': '/home/qian-qi/hepta-utility-36fa-evidence/runtime-materials-restore-86dd-v1/run-v2/ENVIRONMENT_READY.json',
                                  'pin': {'bytes': 21724,
                                          'git_blob': '8b62ac16f554c1f34ee72974637752f5a3b58aec',
                                          'sha256': 'd37a2b3eccf86e42643676d86cf0232ce1931de4693f45bb295761bb42da2172'}},
 'MAINTENANCE_41E_ARTIFACTS': {'path': '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-maintenance-v1/run/ARTIFACTS.json',
                               'pin': {'bytes': 53526,
                                       'git_blob': '222eb4e2913d62cdd308e2ce26edf7c320ebe47f',
                                       'sha256': '4fe039d5630c39af2a05c9ba7a9272cda4bc2a351a81cd253eca7bf21657e706'}},
 'MAINTENANCE_41E_CONFIG': {'path': '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-maintenance-v1/APPROVED_MAINTENANCE_CONFIG.json',
                            'pin': {'bytes': 13693,
                                    'git_blob': '7bddb6c423afbe739bc36a7df2516730911a9337',
                                    'sha256': '3ab98f7c35ce030439773f2035b7d6e4b8f9c4b11b3f6e8f93b431ea369286d7'}},
 'MAINTENANCE_41E_DRIVER': {'path': '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-maintenance-v1/driver-maintenance.py',
                            'pin': {'bytes': 68520,
                                    'git_blob': '59461030d4160f7ad6a978df5a7b6aaeb33fb2a6',
                                    'sha256': '2e8501f584a6905a07124f04bb623c2674c1ec77299b89fbc76ef06610c589ed'}},
 'MAINTENANCE_41E_INPUT_IDENTITIES': {'path': '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-maintenance-v1/run/INPUT_IDENTITIES.json',
                                      'pin': {'bytes': 6256,
                                              'git_blob': '5c0ae8a43544a14461d272e1a0e70bb9ef3b1395',
                                              'sha256': '477d05eb00e62a90f5c187cc18c4ad1401be0b39c289ef5b4dfe1328be96d4bb'}},
 'MATERIALIZATION_3BB_ARTIFACTS': {'path': '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-isolated-materialization-v1/run/ARTIFACTS.json',
                                   'pin': {'bytes': 84294,
                                           'git_blob': '5d2eb472d5651500e02957013e5cdacb3f7b05af',
                                           'sha256': '5b1fbab7087da64bf3b8ee07a3369692158164631549827d2b40ffa94dbe1603'}},
 'MATERIALIZATION_3BB_COMMANDS': {'path': '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-isolated-materialization-v1/run/COMMANDS.json',
                                  'pin': {'bytes': 34319,
                                          'git_blob': 'c3286df54535e30914d1d33e62cd9d19cc8f8246',
                                          'sha256': '65f9f5d52daa905a16f33a2c5966c48ac46ae6d89bba8e0e0dd68dee2d104fb2'}},
 'MATERIALIZATION_3BB_CONFIG': {'path': '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-isolated-materialization-v1/APPROVED_CONFIG.json',
                                'pin': {'bytes': 666,
                                        'git_blob': '42bd8a4df41c9b0bdfceab1487cce4b35da6c585',
                                        'sha256': 'db85c15a435d59560635d728de174f70257985db9a6efcec9ec31f94923eb0d7'}},
 'MATERIALIZATION_3BB_INPUT_IDENTITIES': {'path': '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-isolated-materialization-v1/run/INPUT_IDENTITIES.before.json',
                                          'pin': {'bytes': 3326,
                                                  'git_blob': 'e201c4c7f5fdcb485effad0514c7c51020bd5687',
                                                  'sha256': '1841e53025069346a1c15fb6d9880b93b4018632852b7b91d29c6de5fb3a478d'}},
 'MATERIALIZATION_3BB_MUTATION_INTENTS': {'path': '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-isolated-materialization-v1/run/MUTATION_INTENTS.json',
                                          'pin': {'bytes': 744,
                                                  'git_blob': 'c4a8dbca67be8f9d30367a82e121f1f212532e64',
                                                  'sha256': 'f3e4af4d13cd1bb022d7499e1ce6c4bb55f44ace3834067e23e8a4872b14ca1b'}},
 'MATERIALIZATION_3BB_PACKET': {'path': '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-isolated-materialization-v1/MATERIALIZATION_PACKET.json',
                                'pin': {'bytes': 14404,
                                        'git_blob': 'b05c78c478bbd55219fea7869b1c7871617509c7',
                                        'sha256': 'd1b1a1a77101e3ad1bd27d8d2ac8028ad5610279f6a2c8fc428d3e617c5f574b'}},
 'MATERIALIZER_3BB': {'path': '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-isolated-materialization-v1/driver.py',
                      'pin': {'bytes': 70596,
                              'git_blob': '2044db8282eb8db8d5627519a425a49f636377da',
                              'sha256': 'daf9f1e3b15abddf86a8efe24aa1e034cdc32e15bed35e40df908c2821fa3caf'}}}
ACTUAL_PROOFS = {'archive': {'job_id': '1a1d38b82e9-392-160',
             'result': {'bytes': 17615,
                        'git_blob': '8c5b4818db13a46f990262c02ffe871c8e6f00dc',
                        'sha256': '2814ac7d831b1a306584d5034c6d8781f111ce0ac11e47b7d14b2964ef8d5d72'},
             'result_path': '/home/qian-qi/hepta-utility-36fa-evidence/v8-single-archive-restore-v3/run/RESULT.json',
             'supervisor': {'bytes': 950,
                            'git_blob': 'b5a9b8d0c8e5f9372eac59e3720ba90c42997579',
                            'sha256': '3fc77b2332259fea7142abbc4542ea6a77144cb7f75541b12b3483300e6c4f5d'},
             'supervisor_path': '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-maintenance-v1/V8_RESTORATION_SUPERVISOR.original.json'},
 'final_format': {'job_id': '1a1d4a979d9-392-50f',
                  'result': {'bytes': 7408,
                             'git_blob': '800869ed57256984964dd3c8b9f29e09c496438a',
                             'sha256': '286f9ae45fa594197566eac17ab0806c8ca0d71ef0d329c983d3a9cc7ab9aa7b'},
                  'result_path': '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-nonrust-format-v1/run/RESULT.json',
                  'supervisor': {'bytes': 952,
                                 'git_blob': '0f7aee8fb7c354f234732b5791e78d63671cd894',
                                 'sha256': '816ca8fa765b327ebb42fd304f63e6b8e342f026833c9d080a9320202d7e2f90'},
                  'supervisor_path': '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-canonical-alignment-v1/FINAL_FORMAT_NORMAL.original.json'},
 'maintenance': {'job_id': '1a1d47cebc8-392-41e',
                 'result': {'bytes': 12532,
                            'git_blob': 'b87aed7647ac34e3db0e381110bf685438aee0ee',
                            'sha256': 'fc551cbf01cbc3a113b4039212e6263cf3c59034421dc795ac187248cabac484'},
                 'result_path': '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-maintenance-v1/run/RESULT.json',
                 'supervisor': {'bytes': 956,
                                'git_blob': '70e1866f963a2a2a8d6f3bd468ddd0c291fbf871',
                                'sha256': '865ecacf8f40e4f3e94a92d80adc19190f60d847869394728adfc3a643190b04'},
                 'supervisor_path': '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-nonrust-format-v1/MAINTENANCE_NORMAL.original.json'},
 'materialization': {'job_id': '1a1d468462a-392-3bb',
                     'result': {'bytes': 14663,
                                'git_blob': '30ab4aad6ff10942063da972e02db49629e3809c',
                                'sha256': 'd64b804836db43eac9b178c31059c8d339f2de5cd2d0a3582d64b791ddf451bd'},
                     'result_path': '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-isolated-materialization-v1/run/RESULT.json',
                     'supervisor': {'bytes': 952,
                                    'git_blob': '2a11b4b9e2baa380c247b6a728f90edfbcdcd644',
                                    'sha256': 'fd1140f7bdc02bcc7ea475a15542bd64cfb0d2f23d78dd0708525b49ad214d30'},
                     'supervisor_path': '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-maintenance-v1/MATERIALIZATION_SUPERVISOR.original.json'},
 'runtime': {'job_id': '1a1d0fcb212-2564-1bf4',
             'result': {'bytes': 21366,
                        'git_blob': '7832ed48200e8361ae4a7dd5ca8b7b5f7f289b09',
                        'sha256': '272f2f2719d92b14939273d8807f5d1143b1307b7de78c4499fbfdad10f13a90'},
             'result_path': '/home/qian-qi/hepta-utility-36fa-evidence/runtime-materials-restore-86dd-v1/run-v2/RESULT.json',
             'supervisor': {'bytes': 954,
                            'git_blob': '3705e1ded34c017b57ee9eb13472f67df0da8e20',
                            'sha256': '6709b0594c9649b28cd1d16651b3181458681296cdd2e5d56cf996f16e8deceb'},
             'supervisor_path': '/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/RUNTIME_RESTORATION_SUPERVISOR.original.json'}}
MATERIALIZATION_RECORDS = {'artifact_records': 'MATERIALIZATION_3BB_ARTIFACTS',
 'command_records': 'MATERIALIZATION_3BB_COMMANDS',
 'input_records': 'MATERIALIZATION_3BB_INPUT_IDENTITIES',
 'mutation_records': 'MATERIALIZATION_3BB_MUTATION_INTENTS'}
ARCHIVE_ACTUAL = {'identity': {'bytes': 29366352,
              'git_blob': 'c6941f7873bdfb8ac18577c9844f234e76dc5ed6',
              'sha256': 'a35c75d1f26e6a983885a45b33490a4ebe54f05050568b32b89cfb421b30b583'},
 'path': '/data/hepta-utility-36fa-runtime-materials-86dd-v1/v8-150.4.0-gnu-sandbox/librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz',
 'stat': {'st_ctime_ns': 1794550522509884679,
          'st_dev': 2067,
          'st_gid': 1000,
          'st_ino': 26738823,
          'st_mode': 33152,
          'st_mtime_ns': 1794550522509884679,
          'st_nlink': 1,
          'st_size': 29366352,
          'st_uid': 1000}}
MATERIALIZED_GIT_STATE = {'config_bytes': 123,
 'config_sha256': '5e224c2f489801ee7d2f46cf5c4e40261ea686332bac1588d05a5f463c59f84f',
 'head': 'd25675445c39f76db69a7bd8e71a1a72e1cd5b9f',
 'head_raw_sha256': '576fb0120bbf996a96f0576d0d28b4efad2b90e69fdb6137defefdc1f59fb619',
 'index_bytes': 2080152,
 'index_sha256': 'ac849543b6bbc1f42425d5673f2f7666502dc4d440d7e7a830574a2d84d7b87b',
 'refs_bytes': 0,
 'refs_sha256': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
 'tree': 'a489b394666b8141840275128a780605b024cde0'}
MATERIALIZED_GIT_PIN = {'bytes': 489,
 'git_blob': 'aef9e645b81c2a7f349b11d546c5555b1475c906',
 'sha256': 'a63fa97612dbe0eb6a90da53563a895bcbff187898ef38083df08a18269e8147'}
MAINTENANCE_METADATA_PIN = {'bytes': 2654,
 'git_blob': '42e3986f6a5f06d8518067f0d9dd2ec3e6b46c6a',
 'sha256': '2a980585e50ec38b223fef002990f42e122b7f8a57b49298c32de6c7c67a24b9'}
MAINTENANCE_FINAL_PIN = {'bytes': 5633323,
 'git_blob': '4a77b645fd76a980ef746997efbd09fcd8f233ba',
 'sha256': '981e5971d3e8afc2694bcb1951b0261d24f0238675187005ec8e9bb386a07bf1'}
MAINTENANCE_TREE = 'c026a8d7e93c958b39a36c666debecb3dba4be14'
FINAL_FORMAT_PIN = {'bytes': 5633513,
 'git_blob': 'e3ce3d7bba028e29efca751c6f43fde124b05ea0',
 'sha256': '2e22d929e311bf55beb9c91e91bc191cc15be4bed3c8022e14489df66025f202'}
FINAL_NONRUST_PATHS = ['.github/blob-size-allowlist.txt',
 'CALLERS.toml',
 'qa/b4-no-bypass/PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json',
 'qa/b4-no-bypass/test_resident_provider_local_read_source_closure.py']
CANONICAL_DRIVER_PIN = {'bytes': 46159,
 'git_blob': 'e8d606b801b54ab949c5f215c49cdf47ed0ea89a',
 'sha256': 'f82c0550492a6f6230e29a5047777ec999a563669ec124425a3149b4f115b4e5'}
ORIGINAL_ORDINARY_PACKAGES = ['-p',
 'codex-hepta-agentd',
 '-p',
 'codex-hepta-learning-ledger',
 '-p',
 'codex-hepta-learning-artifacts',
 '-p',
 'codex-hepta-intelligence-eval',
 '-p',
 'codex-hepta-neuron']
WORKFLOW_OVERRIDE_READY = {'final_actual_confirmed': True,
 'original_plan_pin': {'bytes': 28133,
                       'git_blob': '08ffc5c603a4c950cca285ed2b1e479508d8b5ed',
                       'sha256': '40ff9b74214cf1901bd0ac40e416523c73c223ced4271df5c81b9cf964872ea1'},
 'path': '.github/workflows/hepta-daemon-learning-native.yml',
 'reviewed_current_pin': {'bytes': 30745,
                          'git_blob': 'c0012652889b0cca409b27f87bfdc74b234c0fbe',
                          'sha256': '6453782023604b6bb89468611d906e854f0fb79f82f154886225d7765a266aee'}}
FIX_ARGV = ['just',
 'fix',
 '-p',
 'codex-hepta-intelligence-eval',
 '-p',
 'codex-hepta-agentd',
 '-p',
 'codex-hepta-learning-ledger']
FMT_ARGV = ['just', 'fmt', '--base', 'c0f78493f815780f68b9bf5e390a21314d79311f']
MATERIALIZATION_CONTROL = Path('/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-isolated-materialization-v1')
MAINTENANCE_CONTROL = Path('/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-maintenance-v1')
FINAL_FORMAT_CONTROL = Path('/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-nonrust-format-v1')
CANONICAL_CONTROL = Path('/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-canonical-alignment-v1')


HISTORY_EVIDENCE_PARENT = '/home/qian-qi/hepta-utility-36fa-evidence'
HISTORY_TRANSPORT_CONTROL = '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1'
SOURCE_TRANSPORT_CONTROL = '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-v2'
HISTORY_MANIFEST_PATH = '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1/TRANSPORT_MANIFEST.json'
HISTORY_MANIFEST_PIN = {'bytes': 42163,
 'git_blob': '5d2e19cadd569f9dd37f0f87997b115d7ed3ef2a',
 'sha256': '9a7076714a08a5d18094741236f4d5609946f4367d6532150a2d0e9d6c692117'}
HISTORY_ROLES = ['canonical.supervisor',
 'runtime.supervisor',
 'canonical.config',
 'canonical.packet',
 'final_format.supervisor',
 'canonical.driver',
 'canonical.artifacts',
 'canonical.commands',
 'canonical.metadata_delta',
 'canonical.metadata_before_gzip',
 'canonical.metadata_final_gzip',
 'canonical.git_state_final',
 'canonical.index_delta_gzip',
 'canonical.index_audit_gzip',
 'canonical.index_raw_gzip',
 'canonical.inputs',
 'canonical.progress',
 'canonical.result',
 'final_format.config',
 'maintenance.supervisor',
 'final_format.driver',
 'final_format.artifacts',
 'final_format.inputs',
 'final_format.result',
 'final_format.metadata_after_gzip',
 'final_format.metadata_before_gzip',
 'final_format.git_state_final',
 'final_format.inventory_final_gzip',
 'final_format.empty_transition_gzip',
 'materialization.config',
 'materialization.packet',
 'materialization.driver',
 'materialization.artifacts',
 'materialization.commands',
 'materialization.inputs',
 'materialization.mutations',
 'materialization.result',
 'materialization.metadata_final_gzip',
 'maintenance.config',
 'materialization.supervisor',
 'archive.supervisor',
 'maintenance.driver',
 'maintenance.artifacts',
 'maintenance.inputs',
 'maintenance.result',
 'maintenance.metadata_after_gzip',
 'maintenance.metadata_before_gzip',
 'maintenance.git_state_before',
 'maintenance.git_state_final',
 'runtime.environment_ready',
 'runtime.result',
 'archive.readback',
 'archive.artifacts',
 'archive.result',
 'historical_environment.started']
HISTORY_RUNTIME_GUARD_PATH = '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1/historical-runtime-guard.py'
HISTORY_RUNTIME_GUARD_PIN = {'bytes': 70306,
 'git_blob': '917f5b669ce5e4b926c7131a42423a0f069e46a4',
 'sha256': '503aaa202bd40ea54526e11b2e299630b7b888e5afe14a3ce5bfb8a3c1c0f556'}
HISTORY_STAGER_PIN = {'bytes': 17939,
 'git_blob': '0837bd70dd0e20a208fd8f59eec6017910cb9076',
 'sha256': 'cef85f5a2768e11c48303ee3dfffbd41c3393f12b498bba6ad7b6faad4c85763'}
HISTORY_STAGER_ARGV_PIN = {'bytes': 18310,
 'git_blob': 'a85299a968c337037069930c00c66430ec3dc58d',
 'sha256': '1b10521850c52c094d45989095912b5fcfe0687c8bd1119401d7766f4eb5fbfd'}
HISTORY_PACKET_PIN = {'bytes': 10637954,
 'git_blob': '3282998b8de39cc0bcd2c44d40dfd5f9c5b1d57f',
 'sha256': 'da51b174555e0396a524f5f7da2e08e9849039f614efd0e5c7998b11a5fc6cbb'}
HISTORY_GZIP_PIN = {'bytes': 4994854,
 'git_blob': '0f8ff1e10bfbe418c11ff9f3f6844b02817c98b6',
 'sha256': '0fd09793b264476ac6ffda53fa89e38c28e973af32758ce7e2e0932f63275794'}
HISTORY_PART_INPUTS = [{'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-001',
  'pin': {'bytes': 307200,
          'git_blob': '31ab8fbbcd7cc205a6cd1de87d13aecc3b5a4e4e',
          'sha256': '6b86b0391ad498a0a33819ccf3d1f7df85086f7e8c9ee1e7adfbd274e7b0d845'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-002',
  'pin': {'bytes': 307200,
          'git_blob': 'f4b6cfcffb988b79d20e2cb2cdfae9011291e69d',
          'sha256': 'c4380979846fdd7dcbffedc2b31d77afca0ad421ad4e56e5b7482255dc4c25dc'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-003',
  'pin': {'bytes': 307200,
          'git_blob': 'bebb09eefd45b58dce8e8ee5733cfa7b72f4b867',
          'sha256': 'cb4c9818bf745863633d8facec323ad17ab9a79a5174bbc803206d66cb27e088'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-004',
  'pin': {'bytes': 307200,
          'git_blob': '9038f83a3d3749c13eb103d73709ba94627d826f',
          'sha256': 'b9c1c04f9729389996cf2ea77481823b9a0c13b55fc64a280139835fdee6fce1'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-005',
  'pin': {'bytes': 307200,
          'git_blob': '117500db05eb47a4ed5fa15348c2badaf90e8eb9',
          'sha256': '57de91373607f18e1bb495835784555a8c20fed3c35c18568d2f28f25563db6d'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-006',
  'pin': {'bytes': 307200,
          'git_blob': '2bd9985ea771c0a4820461f928019545d5f432e8',
          'sha256': '2c0b8661579fdfc073c934cb6536ac975f0979cf20bbaf6673c8968e4ed73093'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-007',
  'pin': {'bytes': 307200,
          'git_blob': '53b7395b2c06fe97d530300551407dcf93d64a9d',
          'sha256': 'd591844926bf2b70a1c4b1687646e58fed36e5e48e02feb9739fee8306f87ad1'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-008',
  'pin': {'bytes': 307200,
          'git_blob': 'da75e3a2f3f8734a6f75294a94d22da86f851d33',
          'sha256': 'd31c9f29880e7b3f4661a32a2d075252a29e9419940aee6d60690107b2e57ff1'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-009',
  'pin': {'bytes': 307200,
          'git_blob': 'cddcaabf900a5914be150d4932e04a367722ee79',
          'sha256': 'f86dc62e47e9f24bbd9a06cf17eb624a64cce23eca2d89645fd894eba4d44a44'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-010',
  'pin': {'bytes': 307200,
          'git_blob': 'e17216d2dcc28bd08d5290ef1dc3652f685cbb2b',
          'sha256': '3dfa4e0a1a42e0d517e1deed0471b63ab9580dd628d84af1b892b2366215595a'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-011',
  'pin': {'bytes': 307200,
          'git_blob': '021f4f922769f4ed583608695e1ebeaf2e42e5af',
          'sha256': '55db7199ca7b9d776ac22f5546ce9a8c791c639a9a53eeb0ac9d7dc6ee290248'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-012',
  'pin': {'bytes': 307200,
          'git_blob': 'db8238ca9f3a20f7782b4cbe471373f26a60bf1b',
          'sha256': 'ec2b2887b33fe891fdb18596724ca3e6c8899b2e30159021bea5f2afa4df1d72'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-013',
  'pin': {'bytes': 307200,
          'git_blob': 'b24d04d8212983127a63401c05e6937ecdc6cd00',
          'sha256': 'f7c316582236168bbc1ff6fb14c04d4090d0259e103bc51dbf49256bf73e1bcf'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-014',
  'pin': {'bytes': 307200,
          'git_blob': '9e365c121528367edf62cad17251117900cd81a5',
          'sha256': 'e46da201c7353d917a18314e34fcac53ecf20d509ea095fe432d9a36eaf2f1ad'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-015',
  'pin': {'bytes': 307200,
          'git_blob': '355e5c9355e63c7ea23e7ffcd36a424f4dcb810f',
          'sha256': '3059a5c2580412437680096e6068a835e381a0c94e039621e12b6afefd9c5c0f'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-016',
  'pin': {'bytes': 307200,
          'git_blob': '101e78c002ed67a46f597d5cee48c92bb05002bd',
          'sha256': '42dfe642346ff861f9cbb6c3269ae841821dfc8c795f67243444da53e3115dd8'}},
 {'path': '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1.payload.json.gz.part-017',
  'pin': {'bytes': 79654,
          'git_blob': 'aadf21d52a68d116c3c9d022c1b08f7ef827db04',
          'sha256': '2073b0f1f10f06d0b884ac2ab25aad6f0b200c904be1585bc8b38f537bac51d8'}}]
HISTORY_PROOF_ROLES = {'ARCHIVE_V3': ['archive.result', 'archive.supervisor'],
 'CANONICAL_ALIGNMENT': ['canonical.result', 'canonical.supervisor'],
 'FINAL_FORMAT': ['final_format.result', 'final_format.supervisor'],
 'ISOLATED_MATERIALIZATION': ['materialization.result', 'materialization.supervisor'],
 'MAINTENANCE_41E': ['maintenance.result', 'maintenance.supervisor']}
HISTORY_FIXED_ROLES = {'ARCHIVE_V3_ARTIFACTS': 'archive.artifacts',
 'ARCHIVE_V3_READBACK': 'archive.readback',
 'FINAL_FORMAT_ARTIFACTS': 'final_format.artifacts',
 'FINAL_FORMAT_CONFIG': 'final_format.config',
 'FINAL_FORMAT_DRIVER': 'final_format.driver',
 'HISTORICAL_ENVIRONMENT_READY': 'runtime.environment_ready',
 'MAINTENANCE_41E_ARTIFACTS': 'maintenance.artifacts',
 'MAINTENANCE_41E_CONFIG': 'maintenance.config',
 'MAINTENANCE_41E_DRIVER': 'maintenance.driver',
 'MAINTENANCE_41E_INPUT_IDENTITIES': 'maintenance.inputs',
 'MATERIALIZATION_3BB_ARTIFACTS': 'materialization.artifacts',
 'MATERIALIZATION_3BB_COMMANDS': 'materialization.commands',
 'MATERIALIZATION_3BB_CONFIG': 'materialization.config',
 'MATERIALIZATION_3BB_INPUT_IDENTITIES': 'materialization.inputs',
 'MATERIALIZATION_3BB_MUTATION_INTENTS': 'materialization.mutations',
 'MATERIALIZATION_3BB_PACKET': 'materialization.packet',
 'MATERIALIZER_3BB': 'materialization.driver'}
HISTORY_ARTIFACT_ROLES = {'/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-canonical-alignment-v1/run/GIT_METADATA.allowed-actual-delta.json': 'canonical.metadata_delta',
 '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-canonical-alignment-v1/run/GIT_METADATA.before.json.gz': 'canonical.metadata_before_gzip',
 '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-canonical-alignment-v1/run/GIT_METADATA.final.json.gz': 'canonical.metadata_final_gzip',
 '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-canonical-alignment-v1/run/GIT_STATE.final.json': 'canonical.git_state_final',
 '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-canonical-alignment-v1/run/INDEX.complete-entry-delta.json.gz': 'canonical.index_delta_gzip',
 '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-canonical-alignment-v1/run/INDEX.final.audit.json.gz': 'canonical.index_audit_gzip',
 '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-canonical-alignment-v1/run/INDEX.final.raw.gz': 'canonical.index_raw_gzip',
 '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-nonrust-format-v1/run/INPUT_IDENTITIES.json': 'final_format.inputs',
 '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-nonrust-format-v1/run/SOURCE_GIT_METADATA.after.json.gz': 'final_format.metadata_after_gzip',
 '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-nonrust-format-v1/run/SOURCE_GIT_METADATA.before.json.gz': 'final_format.metadata_before_gzip',
 '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-nonrust-format-v1/run/final.git-state.json': 'final_format.git_state_final',
 '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-nonrust-format-v1/run/final.inventory.json.gz': 'final_format.inventory_final_gzip',
 '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-nonrust-format-v1/run/fmt.after.postimages.json.gz': 'final_format.empty_transition_gzip',
 '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-isolated-materialization-v1/run/final.git-metadata.json.gz': 'materialization.metadata_final_gzip',
 '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-maintenance-v1/run/SOURCE_GIT_METADATA.after.json.gz': 'maintenance.metadata_after_gzip',
 '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-maintenance-v1/run/SOURCE_GIT_METADATA.before.json.gz': 'maintenance.metadata_before_gzip',
 '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-maintenance-v1/run/SOURCE_GIT_STATE.before.json': 'maintenance.git_state_before',
 '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-maintenance-v1/run/final.git-state.json': 'maintenance.git_state_final'}


class SourceChanged(RuntimeError):
    pass


def check(value, reason):
    if not value:
        raise RuntimeError(reason)


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def pin(raw, expected, reason):
    check(isinstance(expected, dict) and all(expected.get(k) == v for k, v in identity(raw).items()), reason)
    return raw


def load(path, expected, name):
    raw = Path(path).read_bytes()
    pin(raw, expected, 'exact original module ' + str(path))
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


def exact_pin(value, reason):
    check(isinstance(value, dict) and set(value) == {'bytes', 'sha256', 'git_blob'}
          and type(value['bytes']) is int and value['bytes'] >= 0
          and isinstance(value['sha256'], str) and re.fullmatch('[0-9a-f]{64}', value['sha256'])
          and isinstance(value['git_blob'], str) and re.fullmatch('[0-9a-f]{40}', value['git_blob']), reason)
    return value


def pin_fields(value):
    return {key: value[key] for key in ('bytes', 'sha256', 'git_blob')}


def audited(value, names, reason):
    rows = value.get('final_audits')
    check(isinstance(rows, list) and len(rows) == len(names)
          and len({row['check'] for row in rows}) == len(rows)
          and {row['check']: row['status'] for row in rows} == {name: 'verified' for name in names}, reason)


def artifact_catalog(value, wrapped):
    if wrapped:
        check(isinstance(value, dict) and set(value) == {
            'files', 'terminal_report', 'terminal_report_self_hash_not_included'}
              and value['terminal_report'] == 'RESULT.json'
              and value['terminal_report_self_hash_not_included'] is True, 'original maintenance artifact envelope')
        rows = value['files']
    else:
        rows = value
    check(isinstance(rows, list), 'complete artifact list')
    indexed = {}
    for row in rows:
        name = row.get('name')
        check(isinstance(name, str) and name not in ('', '.', '..') and '/' not in name
              and '\\' not in name and '\0' not in name and name not in indexed,
              'one-level unique original artifact name')
        exact_pin(pin_fields(row), 'complete original artifact pin')
        indexed[name] = row
    return indexed


def canonical_to_v5_projection(canonical):
    """Reconstruct V5 bytes only after retaining the full ownership-bearing input."""
    check(isinstance(canonical, dict) and set(canonical) == {'root', 'files'}
          and canonical['root'] == str(Path(CURRENT_REPO) / '.git'), 'complete canonical Git metadata envelope')
    common = {'path', 'kind', 'mode', 'uid', 'gid', 'device', 'inode', 'nlink', 'mtime_ns', 'ctime_ns'}
    rows = canonical['files']
    check(isinstance(rows, list), 'complete canonical metadata rows')
    indexed, children = {}, {}
    for row in rows:
        path = row.get('path')
        check(isinstance(path, str) and '\0' not in path and '\\' not in path,
              'canonical metadata path text')
        path.encode('utf-8', 'strict')
        parts = path.split('/')
        check(all(part not in ('', '.', '..') for part in parts) and path not in indexed,
              'safe unique canonical metadata path')
        check(row.get('kind') in ('file', 'directory')
              and set(row) == common | ({'bytes', 'sha256'} if row['kind'] == 'file' else set()),
              'exact canonical metadata row fields')
        check(all(type(row[key]) is int and row[key] >= 0 for key in (
            'mode', 'uid', 'gid', 'device', 'inode', 'nlink', 'mtime_ns', 'ctime_ns')),
              'complete exact integer canonical ownership and stat fields')
        check(row['mode'] <= 0o7777 and row['nlink'] >= 1, 'canonical metadata mode and links')
        if row['kind'] == 'file':
            check(type(row['bytes']) is int and row['bytes'] >= 0
                  and isinstance(row['sha256'], str) and re.fullmatch('[0-9a-f]{64}', row['sha256']),
                  'complete canonical metadata file identity')
        indexed[path] = row
        children.setdefault('/'.join(parts[:-1]), []).append(path)
    check(rows == sorted(rows, key=lambda row: os.fsencode(row['path'])), 'canonical complete path order')
    for path in indexed:
        parent = path.rpartition('/')[0]
        check(not parent or parent in indexed and indexed[parent]['kind'] == 'directory',
              'canonical metadata parent directory closure')
    result = []
    def visit(parent):
        for path in sorted(children.get(parent, []), key=lambda item: os.fsencode(item.rsplit('/', 1)[-1])):
            row = indexed[path]
            result.append({key: value for key, value in row.items() if key not in ('uid', 'gid')})
            if row['kind'] == 'directory':
                visit(path)
    visit('')
    check(len(result) == len(rows), 'complete V5 DFS projection')
    value = {'format': 'hepta-source-git-metadata-inventory-v1', 'root': canonical['root'], 'files': result}
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()


def stable_canonical_metadata(root):
    """Observe every real Git entry, including uid/gid; no metadata writes."""
    root = Path(root)
    check(str(root) == str(Path(CURRENT_REPO) / '.git'), 'fixed current Git metadata root')
    rows = []
    def full_stat(info):
        return (info.st_mode, info.st_uid, info.st_gid, info.st_dev, info.st_ino,
                info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    def visit(directory):
        before_dir = directory.lstat()
        check(stat.S_ISDIR(before_dir.st_mode), 'real Git metadata directory')
        with os.scandir(directory) as scan:
            entries = sorted(list(scan), key=lambda entry: os.fsencode(entry.name))
        for entry in entries:
            path = Path(entry.path)
            observed = path.lstat()
            row = {'path': path.relative_to(root).as_posix(), 'mode': stat.S_IMODE(observed.st_mode),
                   'uid': observed.st_uid, 'gid': observed.st_gid, 'device': observed.st_dev,
                   'inode': observed.st_ino, 'nlink': observed.st_nlink,
                   'mtime_ns': observed.st_mtime_ns, 'ctime_ns': observed.st_ctime_ns}
            if stat.S_ISDIR(observed.st_mode):
                row['kind'] = 'directory'
                rows.append(row)
                visit(path)
                check(full_stat(path.lstat()) == full_stat(observed), 'Git directory remained stable')
            else:
                check(stat.S_ISREG(observed.st_mode), 'canonical Git metadata only real regular files')
                digest, size = hashlib.sha256(), 0
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, 'rb') as stream:
                    opened = os.fstat(stream.fileno())
                    check(full_stat(opened) == full_stat(observed), 'Git file lstat/open identity')
                    for chunk in iter(lambda: stream.read(1048576), b''):
                        digest.update(chunk)
                        size += len(chunk)
                    finished = os.fstat(stream.fileno())
                check(full_stat(observed) == full_stat(opened) == full_stat(finished)
                      == full_stat(path.lstat()) and size == observed.st_size,
                      'complete Git file ownership, mode, identity and bytes stable during read')
                row.update(kind='file', bytes=size, sha256=digest.hexdigest())
                rows.append(row)
        with os.scandir(directory) as scan:
            after_names = sorted((entry.name for entry in scan), key=os.fsencode)
        check(after_names == [entry.name for entry in entries]
              and full_stat(directory.lstat()) == full_stat(before_dir), 'complete Git directory membership stable')
    visit(root)
    value = {'root': str(root), 'files': sorted(rows, key=lambda row: os.fsencode(row['path']))}
    canonical_to_v5_projection(value)
    return value


def physical_projection(value):
    rows = {}
    check(isinstance(value, dict) and value.get('tracked_entries') == 15243
          and value.get('filesystem_entries') == 15243 and isinstance(value.get('files'), list),
          'complete final physical source membership')
    for row in value['files']:
        path = row['path']
        check(isinstance(path, str) and '\0' not in path and not path.startswith('/')
              and all(part not in ('', '.', '..', '.git') for part in path.split('/'))
              and path not in rows, 'safe unique full physical source path')
        check(row['kind'] in ('file', 'symlink') and row['stable'] is True, 'supported stable physical leaf')
        rows[path] = {key: item for key, item in row.items()
                      if key not in ('index_blob', 'index_mode', 'matches_index')}
    check(len(rows) == 15243, 'all actual physical leaves')
    return rows


def native_projection(value):
    # Exact original b92/972ec projection: default ensure_ascii, compact, no LF.
    rows = [{'path': row['path'], 'mode': row['index_mode'], 'bytes': row['bytes'],
             'sha256': row['sha256'], 'blob': row['working_blob']} for row in value['files']]
    rows.sort(key=lambda row: os.fsencode(row['path']))
    return json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()


def metadata_file_projection(value):
    """Compare 3bb's six actual file rows with V5's complete DFS envelope."""
    check(set(value) == {'format', 'root', 'files'}
          and value['format'] == 'hepta-source-git-metadata-inventory-v1'
          and value['root'] == str(Path(CURRENT_REPO) / '.git'), 'original V5 metadata envelope')
    result = {}
    for row in value['files']:
        check(row['path'] not in result, 'unique original V5 metadata rows')
        result[row['path']] = row
    return {path: row for path, row in result.items() if row['kind'] == 'file'}


def require_stage(stage, name, argv, seconds):
    check(stage['name'] == name and stage['argv'] == argv and stage['timeout_seconds'] == seconds
          and stage['working_directory'] == CURRENT_REPO and stage['maximum_log_bytes'] == 67108864
          and stage['command_returned'] is True and stage['execution_outcome'] == 'completed'
          and stage['status'] == 'completed_review_required' and stage['raw_log_retained'] is True
          and stage['retention']['complete'] is True and stage['test_command'] is False,
          'original maintenance command, complete output and retention')
    execution = stage['execution']
    check(execution['returncode'] == 0 and execution['timed_out'] is False
          and execution['output_limit_exceeded'] is False
          and execution['observed_passed_tests'] == execution['observed_failed_tests'] == 0,
          'actual normal maintenance command; no test result inferred')



class Admission:
    def __init__(self, cfg, output, runtime):
        check(cfg.get('state') == 'READY_FOR_FINAL_SOURCE_QUALIFICATION'
              and cfg.get('root_execution_approved') is True, 'final source input remains HOLD')
        self._require_complete_bindings(cfg)
        self._require_transport_bindings(cfg)
        self.cfg = cfg
        self.output = Path(output)
        self.lease = None
        self.runtime = runtime
        self._fixed_raw = {}
        self._transport_stats = {}
        os.environ['GIT_OPTIONAL_LOCKS'] = '0'
        os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
        sys.dont_write_bytecode = True
        self.h = load(cfg['historical_runtime_guard_path'], HISTORY_RUNTIME_GUARD_PIN, 'fixed_history_transport_v5_historical_runtime_environment')
        self.m = load(cfg['maintenance_guard_path'], V5_PIN, 'original_v5_current_source_observation')
        m = self.m
        check(str(m.REPO) == str(self.h.REPO) == HISTORICAL_REPO
              and str(m.TARGET) == str(self.h.TARGET) == cfg['target'], 'original V5 historical source/target constants')
        # Keep all historical subjects and guard statements; only four closed historical read locations differ.
        m.REPO = Path(cfg['repo']); m.HEAD = cfg['source']; m.TREE = cfg['tree']
        m.OUT = self.output
        m.cfg = cfg['runtime_guard']
        self.h.OUT = self.output / 'historical-runtime'
        self.h.cfg = cfg['runtime_guard']
        check(m.cfg == RUNTIME_GUARD, 'complete original environment/target/runtime proof contract')
        m.real_directory(self.output.parent)
        os.mkdir(self.output, 0o700)
        os.mkdir(self.h.OUT, 0o700)
        self.inventory = load(cfg['inventory_driver_path'], INVENTORY_PIN, 'original_full_inventory_for_qualification')
        self.initial_raw = None
        self.environment = None
        self.initial_git = None
        self.initial_metadata = None
        self.initial_metadata_v5 = None
        m.read_input(cfg['maintenance_guard_path'], V5_PIN)
        m.read_input(cfg['inventory_driver_path'], INVENTORY_PIN)
        self.h.read_input(cfg['maintenance_guard_path'], V5_PIN)
        self.h.read_input(cfg['historical_runtime_guard_path'], HISTORY_RUNTIME_GUARD_PIN)
        self._history_rows = self._load_transport_manifest()

    def read(self, path, expected, name):
        raw = self.m.read_input(path, expected)
        self.m.write(name, raw)
        return self.m.parse(raw)

    def observed_proof(self, value, prefix):
        check(prefix in HISTORY_PROOF_ROLES, 'fixed historical result/supervisor role pair')
        result_role, supervisor_role = HISTORY_PROOF_ROLES[prefix]
        original = self.read_historical(result_role, value['result_path'], value['result'], prefix + '.RESULT.original.json')
        raw = self._read_historical(supervisor_role, value['supervisor_path'], value['supervisor'])
        terminal = self.m.parse_supervisor(raw)
        check(terminal['job_id'] == value['job_id'], prefix + ' exact actual job')
        self.m.write(prefix + '.SUPERVISOR.original.json', raw)
        return original

    def current_lock(self):
        expected = self.cfg['coordination_lock']
        info = os.fstat(self.lease)
        observed = {'device': info.st_dev, 'inode': info.st_ino, 'uid': info.st_uid,
                    'mode': stat.S_IMODE(info.st_mode), 'nlink': info.st_nlink}
        check(stat.S_ISREG(info.st_mode) and all(expected[k] == v for k, v in observed.items()),
              'same real task source coordination lock')
        fresh = Path(expected['path']).lstat()
        check(fresh.st_dev == info.st_dev and fresh.st_ino == info.st_ino and not stat.S_ISLNK(fresh.st_mode),
              'coordination lock path still names acquired inode')
        return observed

    def acquire_and_validate(self):
        m, cfg = self.m, self.cfg
        self.lease = os.open(cfg['coordination_lock']['path'], os.O_RDONLY | os.O_NOFOLLOW)
        fcntl.flock(self.lease, fcntl.LOCK_SH | fcntl.LOCK_NB)
        m.jwrite('SOURCE_COORDINATION_SH.json', {'path': cfg['coordination_lock']['path'],
                 **self.current_lock(), 'at': m.now(), 'pid': os.getpid(), 'fd': self.lease,
                 'scope': 'Only cooperative source writers; complete actual source checks remain required.'})
        self._require_transport_staging()
        plan = self.read(cfg['plan_path'], PLAN_PIN, 'PLAN.original.json')
        check(plan['schema'] == 'hepta.utility.exact-source-qualification-plan.v2', 'original reviewed qualification plan')
        aligned = self.observed_proof(cfg['canonical_alignment'], 'CANONICAL_ALIGNMENT')
        self.materialized = self.validate_materialization(aligned)
        self._validate_archive()
        maintenance = self._validate_maintenance(self.materialized)
        final_format, final_raw, final_metadata = self._validate_final_format(maintenance)
        self.initial_git = m.git_state()
        check(self.initial_git == aligned['after']['git_state'] == cfg['current_final_git_state'],
              'current raw Git baseline is the actual canonical endpoint, not materialization')
        m.jwrite('GIT_STATE.before.json', self.initial_git)
        self.initial_raw = self.inventory.inventory(Path(cfg['repo']))
        pin(self.initial_raw, cfg['full_physical_inventory'], 'current complete source equals actual clean alignment')
        self.inventory.require_inventory(self.initial_raw, {'source_sha': cfg['source'], 'source_tree': cfg['tree']})
        value = m.parse(self.initial_raw)
        physical_projection(value)
        check(value['source'] == {'head': cfg['source'], 'tree': cfg['tree'], 'status': ''}
              and all(row['matches_index'] is True for row in value['files']), 'complete canonical source is clean')
        self._validate_canonical(aligned, final_format, final_raw, final_metadata, value)
        projected = native_projection(value)
        pin(projected, cfg['full_native_inventory'], 'original native five-field projection of complete clean source')
        check(hashlib.sha256(projected).hexdigest() == cfg['expected_inventory_sha256'], 'original native expected digest')
        m.gzrecord('SOURCE_INITIAL.complete.inventory.json.gz', self.initial_raw)
        m.gzrecord('SOURCE_INITIAL.native-projection.json.gz', projected)
        self._validate_source_controls(plan, value)
        m.read_input(cfg['native_driver_path'], plan['unchanged_original_controls']['native_driver'])
        if self.runtime:
            self.environment = self.h.environment_preflight()
            desired = cfg['runtime_guard']['environment']
            external = {'target': m.external_directory(m.TARGET, 'current source external target')}
            for name in ('UV_PROJECT_ENVIRONMENT', 'UV_CACHE_DIR', 'RUFF_CACHE_DIR'):
                external[name] = m.external_directory(desired[name], 'current source external ' + name)
            m.jwrite('CURRENT_SOURCE_EXTERNAL_DIRECTORIES.json', external)
        else:
            self.h.validate_runtime_restoration()
            self.environment = {'source_gates_only': True}
        self._require_live_metadata('GIT_METADATA.admission')
        check(m.git_state() == self.initial_git, 'canonical Git unchanged through admission')
        m.jwrite('ADMISSION.json', {'status': 'actual_clean_final_source_admitted',
                 'source': cfg['source'], 'tree': cfg['tree'], 'parents': cfg['parents'],
                 'full_initial_inventory': cfg['full_physical_inventory'],
                 'native_snapshot_sha256': cfg['expected_inventory_sha256'], 'qualification': False, 'at': m.now(),
                 'historical_source_repo': HISTORICAL_REPO, 'provenance_donor_repo': DONOR_REPO,
                 'actual_isolated_materialization': cfg['isolated_materialization'],
                 'actual_maintenance': cfg['actual_maintenance'], 'actual_final_format': cfg['final_format'],
                 'actual_canonical_alignment': cfg['canonical_alignment'],
                 'root_workflow_parent_count': 48})
        return self

    def validate_materialization(self, aligned):
        """Bind the actual d256 start, without identifying it with the final endpoint."""
        proof = self.cfg['isolated_materialization']
        value = self._observed_known('materialization', proof, 'ISOLATED_MATERIALIZATION')
        packet = self._fixed_json('MATERIALIZATION_3BB_PACKET')
        self._fixed('MATERIALIZER_3BB')
        self._fixed('MATERIALIZATION_3BB_CONFIG')
        records = {key: self._fixed_json(name) for key, name in MATERIALIZATION_RECORDS.items()}
        self._check_materialization(value, packet, records)
        catalog = artifact_catalog(records['artifact_records'], False)
        metadata_raw = self._artifact(catalog, MATERIALIZATION_CONTROL / 'run', 'final.git-metadata.json.gz',
                                      'MATERIALIZATION_GIT_METADATA', proof['git_metadata'])
        pin(metadata_raw, proof['git_metadata'], 'actual complete new materialization metadata')
        self.materialization_metadata = self.m.parse(metadata_raw)
        check(isinstance(self.materialization_metadata, list)
              and len(self.materialization_metadata) == 6, 'original complete six materialization Git files')
        check(aligned['before']['commit'] == MATERIALIZED_SUBJECT['commit']
              and aligned['before']['tree'] == MATERIALIZED_SUBJECT['tree']
              and aligned['before']['parents'] == MATERIALIZED_SUBJECT['parents'],
              'canonical begins at the materialized commit after separately reviewed maintenance')
        return value


    def before_native_stage(self, name):
        active = self.m.active_build_processes()
        self.m.jwrite(name + '.BUILD_PROCESS_PREFLIGHT.json', active)
        check(not active['active_matching_processes'] and not active['unreadable_matching_processes'],
              'active/unknown same-UID build/formatter process before ' + name)
        check(self.m.verify_original_inputs()['unchanged'] is True, 'original inputs before native stage')
        check(self.h.verify_original_inputs()['unchanged'] is True, 'historical runtime proof inputs before native stage')
        self.current_lock()
        self._verify_transport_stability()

    def finish(self):
        self.current_lock()
        self._verify_transport_stability()
        self.m.verify_original_inputs()
        self.h.verify_original_inputs()
        self.h.jwrite('INPUTS.final.json', self.h.input_pins)
        self.h.jwrite('READONLY_COMMANDS.json', self.h.commands)
        current_git = self.m.git_state()
        self.m.jwrite('GIT_STATE.after.json', current_git)
        if current_git != self.initial_git:
            raise SourceChanged('actual raw Git state changed during qualification')
        self._require_live_metadata('GIT_METADATA.after')
        raw = self.inventory.inventory(Path(self.cfg['repo']))
        self.m.gzrecord('SOURCE_FINAL.complete.inventory.json.gz', raw)
        value = json.loads(raw)
        if value['source'] != {'head': self.cfg['source'], 'tree': self.cfg['tree'], 'status': ''}:
            raise SourceChanged('final source identity changed')
        original = {r['path']: r for r in json.loads(self.initial_raw)['files']}
        actual = {r['path']: r for r in value['files']}
        if len(actual) != len(value['files']):
            raise SourceChanged('duplicate physical source inventory path')
        for path, before in original.items():
            if path not in actual or actual[path] != before:
                raise SourceChanged('source-controlled full inventory row changed: ' + path)
        extras = [r for r in value['files'] if r['path'] not in original]
        # The original b92 native snapshot separately enforces tracked/nonignored
        # equality. Preserve actual ignored JUnit/output entries rather than
        # silently calling this full physical inventory unchanged.
        self.m.jwrite('FULL_PHYSICAL_COMPARISON.json', {'original_rows_identical': True,
                     'full_bytes_equal': raw == self.initial_raw,
                     'additional_physical_entries': extras,
                     'scope': 'Original native snapshot equality is a separate required gate; actual generated outputs remain visible.'})
        self.m.jwrite('INPUTS.final.json', self.m.input_pins)
        self.m.jwrite('READONLY_COMMANDS.json', self.m.commands)
        return {'original_source_rows_unchanged': True, 'extra_physical_entries': len(extras),
                'full_physical_bytes_equal': raw == self.initial_raw}

    def close(self):
        if self.lease is not None:
            os.close(self.lease)
            self.lease = None


    @staticmethod
    def _require_complete_bindings(cfg):
        check(cfg.get('historical_source_repo') == HISTORICAL_REPO
              and cfg.get('provenance_donor_repo') == DONOR_REPO and cfg.get('repo') == CURRENT_REPO,
              'three distinct original repository roles')
        check(cfg.get('expected_canonical_subject') == FINAL_SUBJECT
              and cfg.get('source') == FINAL_SUBJECT['commit'] and cfg.get('tree') == FINAL_SUBJECT['tree']
              and cfg.get('parents') == FINAL_SUBJECT['parents'] and cfg.get('expected_file_count') == 15243,
              'actual final source must bind the reviewed immutable canonical subject')
        check(cfg.get('materialized_subject') == MATERIALIZED_SUBJECT and cfg.get('runtime_guard') == RUNTIME_GUARD
              and cfg.get('coordination_lock') == COORDINATION_LOCK,
              'original materialized start, complete runtime contract and coordination inode')
        for key in ('full_physical_inventory', 'full_native_inventory'):
            exact_pin(cfg.get(key), 'actual canonical ' + key + ' required')
        check(cfg.get('expected_inventory_sha256') == cfg['full_native_inventory']['sha256'], 'one native expected digest')
        proof = cfg.get('canonical_alignment')
        check(isinstance(proof, dict) and isinstance(proof.get('job_id'), str) and proof['job_id']
              and proof.get('result_path') == str(CANONICAL_CONTROL / 'run' / 'RESULT.json')
              and isinstance(proof.get('supervisor_path'), str) and Path(proof['supervisor_path']).is_absolute(),
              'actual canonical terminal proof remains required')
        for key in ('result', 'supervisor', 'artifacts', 'before_git_metadata_raw', 'final_git_metadata_raw',
                    'final_index_raw', 'final_index_audit', 'complete_entry_delta', 'allowed_metadata_delta',
                    'commands', 'progress', 'inputs', 'approved_config', 'canonical_packet'):
            exact_pin(proof.get(key), 'actual canonical ' + key + ' remains required')
        check(isinstance(cfg.get('current_final_git_state'), dict)
              and cfg.get('canonical_complete_git_metadata') == proof['final_git_metadata_raw']
              and cfg.get('canonical_original_index') == proof['final_index_raw'], 'one complete canonical Git baseline')
        check(cfg.get('actual_final_format_postimages_reviewed') is True
              and cfg.get('actual_final_fences_reviewed') is True
              and cfg.get('reviewed_formatter_changed_paths') == [], 'actual final source reviews required')
        check(cfg.get('source_control_pin_overrides') == [WORKFLOW_OVERRIDE_READY], 'one explicit workflow successor pin')
        for key in ('plan_path', 'native_driver_path', 'maintenance_guard_path', 'inventory_driver_path'):
            check(isinstance(cfg.get(key), str) and Path(cfg[key]).is_absolute(), 'fixed staged original control ' + key)


    def _fixed(self, name):
        if name not in self._fixed_raw:
            spec = FIXED_INPUTS[name]
            raw = self._read_historical(HISTORY_FIXED_ROLES[name], spec['path'], spec['pin'])
            self._fixed_raw[name] = raw
        return self._fixed_raw[name]


    def _fixed_json(self, name):
        return self.m.parse(self._fixed(name))


    def _observed_known(self, name, proof, prefix):
        expected = ACTUAL_PROOFS[name]
        check(all(proof.get(key) == expected[key] for key in (
            'result_path', 'result', 'supervisor_path', 'supervisor', 'job_id')), 'exact actual ' + name + ' proof')
        return self.observed_proof(proof, prefix)


    def _artifact(self, catalog, root, name, output, raw_pin=None):
        check(name in catalog, 'complete original artifact: ' + name)
        row = catalog[name]
        original_path = str(Path(root) / name)
        check(original_path in HISTORY_ARTIFACT_ROLES, 'one fixed original artifact role')
        raw = self._read_historical(HISTORY_ARTIFACT_ROLES[original_path], original_path, pin_fields(row))
        if name.endswith('.gz'):
            expected = {'bytes': row['raw_bytes'], 'sha256': row['raw_sha256'], 'git_blob': row['raw_git_blob']}
            exact_pin(expected, 'original gzip full raw identity')
            check(expected['bytes'] <= 40000000, 'original V5 input bound for decoded proof')
            with gzip.GzipFile(fileobj=io.BytesIO(raw), mode='rb') as stream:
                decoded = stream.read(expected['bytes'] + 1)
            pin(decoded, expected, 'complete decoded original artifact: ' + name)
            raw = decoded
        if raw_pin is not None:
            pin(raw, raw_pin, output + ': explicit original raw artifact binding: ' + name)
        return raw


    @staticmethod
    def _check_materialization(value, packet, records):
        check(packet['source_repo'] == DONOR_REPO and packet['destination_repo'] == CURRENT_REPO
              and {key: packet['current'][key] for key in ('commit', 'tree', 'parents')} == MATERIALIZED_SUBJECT,
              'exact donor and materialized subject')
        check(value['format'] == 'hepta-complete-candidate-materialization-result-v1'
              and value['status'] == 'MATERIALIZED_EXACT_CANDIDATE_FOR_MAINTENANCE_REVIEW_ONLY'
              and value['source_repo'] == DONOR_REPO and value['destination_repo'] == CURRENT_REPO
              and value['source_commit'] == MATERIALIZED_SUBJECT['commit']
              and value['source_tree'] == MATERIALIZED_SUBJECT['tree']
              and value['parents'] == MATERIALIZED_SUBJECT['parents'], 'actual materialization producer roles')
        for key in ('new_repo_created', 'action_completed', 'new_files_and_directories_synced',
                    'donor_physical_and_git_file_state_unchanged', 'input_identities_unchanged'):
            check(value.get(key) is True, 'actual materialization ' + key)
        for key in ('qualification', 'old_source_writes', 'remote_ref_updates', 'cargo_or_formatter_started',
                    'dependency_installation_started', 'automatic_retry', 'rollback'):
            check(value.get(key) is False, 'materialization did not authorize ' + key)
        check(value['test_commands_dispatched'] == 0 and value['physical_leaves_created'] == 15243
              and value['new_objects_fully_verified'] == 16661 and value['donor_objects_fully_verified'] == 16449
              and value['cleanup_errors'] == [] and not any(key in value for key in ('error', 'retention_error')),
              'complete materialization object/leaf/cleanup observations')
        audited(value, ['donor_physical_source_and_git_files', 'new_source_and_git', 'inputs_and_coordination'],
                'all original materialization audits')
        current = value['current_source_after']
        check(value['current_source_before'] == current
              and current['head'] == MATERIALIZED_SUBJECT['commit']
              and current['tree'] == MATERIALIZED_SUBJECT['tree'] and current['parents'] == MATERIALIZED_SUBJECT['parents']
              and current['status'] == '' and pin_fields(current['inventory']) == packet['current']['inventory']
              and current['inventory']['filesystem_entries'] == current['inventory']['tracked_entries'] == 15243
              and current['native_inventory'] == packet['current']['native_inventory'], 'complete actual materialized start')
        state = value['current_git_state_after']
        check(value['current_git_state_before'] == state and set(state) == {
            'head_raw_sha256', 'head', 'tree', 'index_bytes', 'index_sha256',
            'config_bytes', 'config_sha256', 'refs_bytes', 'refs_sha256'}
              and state['head'] == current['head'] and state['tree'] == current['tree']
              and state['refs_bytes'] == 0 and state['refs_sha256'] == hashlib.sha256(b'').hexdigest(),
              'actual detached materialization Git state')
        index = value['current_index']
        check(index['raw']['bytes'] == state['index_bytes'] and index['raw']['sha256'] == state['index_sha256']
              and index['entries'] == 15243 and index['all_entry_logical_identities_verified'] is True
              and index['all_actual_stat_fields_verified'] is True
              and index['assume_unchanged_or_skip_worktree_entries'] == 0
              and [row['name'] for row in index['extensions']] == ['TREE'], 'original normal materialized index')
        expected_scope = dict(packet['object_scope'], complete_ancestry=False,
                              donor_objects_must_be_read_from_git_bodies=16449, format_base_leaf_identities_verified=True)
        check(value['object_scope'] == expected_scope
              and expected_scope['counts'] == {'blob': 14805, 'tree': 1852, 'commit': 4}
              and expected_scope['union_objects'] == 16661, 'exact four-snapshot closure, not complete ancestry')
        check(value['donor_source_before'] == value['donor_source_after']
              and value['donor_source_after']['present'] == 15188 and value['donor_source_after']['missing'] == []
              and value['donor_source_after']['native_inventory'] == packet['donor']['native_inventory']
              and value['donor_git_state_before'] == value['donor_git_state_after'], 'unchanged original clean donor')
        donor_git = value['donor_git_state_after']
        check(set(donor_git) == set(packet['donor_git']) | {'git_state', 'refs'}
              and all(donor_git[key] == item for key, item in packet['donor_git'].items())
              and donor_git['git_state'] == packet['donor_proof']['current_git_state'], 'complete declared donor Git proof')
        lock = value['coordination_lock']
        check(lock['path'] == COORDINATION_LOCK['path'] and lock['mode'] == 'LOCK_EX'
              and all(lock['stat'][a] == COORDINATION_LOCK[b] for a, b in (
                  ('st_dev', 'device'), ('st_ino', 'inode'), ('st_uid', 'uid'), ('st_nlink', 'nlink')))
              and stat.S_IMODE(lock['stat']['st_mode']) == COORDINATION_LOCK['mode'], 'same actual EX inode')
        for key, name in MATERIALIZATION_RECORDS.items():
            check(pin_fields(value[key]) == FIXED_INPUTS[name]['pin'], 'exact original materialization record ' + key)
        check(records['command_records'] and all(row.get('actual_terminal') == 'observed'
              and row.get('returncode') == 0 and row.get('timed_out') is False
              for row in records['command_records']), 'all actual materialization command terminals')
        check([row['kind'] for row in records['mutation_records']] == [
            'create_new_repository', 'write_exact_new_physical_source_and_standard_pack',
            'import_independent_standard_pack', 'new_index_and_detached_head']
              and all(row['actual_terminal'] == 'observed' for row in records['mutation_records']),
              'four original scoped mutation terminals')
        for name in ('MATERIALIZER_3BB', 'MATERIALIZATION_3BB_PACKET', 'MATERIALIZATION_3BB_CONFIG'):
            spec = FIXED_INPUTS[name]
            check(records['input_records'][spec['path']] == spec['pin'], 'exact approved materialization input')


    def _validate_archive(self):
        proof = self.cfg['archive_restoration']
        value = self._observed_known('archive', proof, 'ARCHIVE_V3')
        readback = self._fixed_json('ARCHIVE_V3_READBACK')
        original_catalog = self._fixed_json('ARCHIVE_V3_ARTIFACTS')
        check(set(original_catalog) == {'files', 'terminal_report'}
              and original_catalog['terminal_report'] == 'RESULT.json', 'original archive artifact envelope')
        catalog = artifact_catalog(original_catalog['files'], False)
        check(pin_fields(catalog['ARCHIVE_READBACK.json']) == FIXED_INPUTS['ARCHIVE_V3_READBACK']['pin'],
              'original archive readback is in the actual complete catalog')
        environment = self._fixed_json('HISTORICAL_ENVIRONMENT_READY')
        self._check_archive(value, readback, environment)
        self.m.jwrite('ARCHIVE_HISTORY_AND_CURRENT_CONTRACT.json', {
            'historical_environment': FIXED_INPUTS['HISTORICAL_ENVIRONMENT_READY']['pin'],
            'actual_archive_restore': proof, 'projection_fields': ['path', 'resolved', 'bytes', 'sha256', 'mode'],
            'historical_stat_rewritten': False, 'live_environment_check': 'original unchanged V5 environment_preflight'})


    @staticmethod
    def _check_archive(value, readback, environment):
        check(value['format'] == 'hepta-v8-single-archive-restoration-result-v1'
              and value['status'] == 'ARCHIVE_RESTORED_FOR_REVIEW_ONLY'
              and value['source_repo'] == DONOR_REPO and value['source_commit'] == DONOR_SUBJECT['commit']
              and value['source_tree'] == DONOR_SUBJECT['tree'], 'independent archive restoration provenance')
        for key in ('source_unchanged', 'destination_created', 'downloads_started', 'publication_intent_recorded'):
            check(value[key] is True, 'actual archive restoration ' + key)
        for key in ('source_writes', 'environment_changes', 'dependency_installation', 'native_main_started',
                    'automatic_retry', 'qualification'):
            check(value[key] is False, 'archive restoration did not authorize ' + key)
        check(value['cargo_or_test_commands'] == [], 'archive restoration ran no Cargo/test command')
        audited(value, ['source', 'inputs_environment', 'materials'], 'complete actual archive restoration audits')
        materials = next(row for row in value['final_audits'] if row['check'] == 'materials')
        check(readback == value['archive_actual'] == materials['archive'] == ARCHIVE_ACTUAL,
              'complete original new archive identity and stat')
        observed = {'path': readback['path'], 'resolved': readback['path'],
                    'bytes': readback['identity']['bytes'], 'sha256': readback['identity']['sha256'],
                    'mode': stat.S_IMODE(readback['stat']['st_mode'])}
        old = environment['tool_and_material_files']['v8-sandbox-archive']
        check(observed == RUNTIME_GUARD['v8_files']['RUSTY_V8_ARCHIVE']
              == {key: old[key] for key in observed}, 'original five-field content projection, no historical inode rewrite')


    def _validate_maintenance(self, materialized):
        value = self._observed_known('maintenance', self.cfg['actual_maintenance'], 'MAINTENANCE_41E')
        self._fixed('MAINTENANCE_41E_DRIVER')
        original_cfg = self._fixed_json('MAINTENANCE_41E_CONFIG')
        inputs = self._fixed_json('MAINTENANCE_41E_INPUT_IDENTITIES')
        catalog = artifact_catalog(self._fixed_json('MAINTENANCE_41E_ARTIFACTS'), True)
        self._check_maintenance(value, materialized, original_cfg, inputs)
        initial = catalog['SOURCE.before.inventory.json.gz']
        check({key: initial['raw_' + key] for key in ('bytes', 'sha256', 'git_blob')}
              == pin_fields(materialized['current_source_after']['inventory']),
              'pinned original maintenance catalog and RESULT retain the complete materialized starting inventory')
        before = self._artifact(catalog, MAINTENANCE_CONTROL / 'run', 'SOURCE_GIT_METADATA.before.json.gz',
                                'MAINTENANCE_GIT_METADATA_BEFORE', MAINTENANCE_METADATA_PIN)
        after = self._artifact(catalog, MAINTENANCE_CONTROL / 'run', 'SOURCE_GIT_METADATA.after.json.gz',
                               'MAINTENANCE_GIT_METADATA_AFTER', MAINTENANCE_METADATA_PIN)
        check(before == after, 'complete maintenance Git metadata unchanged')
        v5_files = metadata_file_projection(self.m.parse(before))
        check(set(v5_files) == {row['path'] for row in self.materialization_metadata}, 'six actual Git file paths bridge')
        for row in self.materialization_metadata:
            observed = v5_files[row['path']]
            expected = {'path': row['path'], 'kind': 'file', 'bytes': row['bytes'], 'sha256': row['sha256'],
                        'mode': stat.S_IMODE(row['stat']['st_mode'])}
            expected.update({a: row['stat'][b] for a, b in [('device', 'st_dev'), ('inode', 'st_ino'),
                ('nlink', 'st_nlink'), ('mtime_ns', 'st_mtime_ns'), ('ctime_ns', 'st_ctime_ns')]})
            check(observed == expected, 'every actual materialization file field retained by maintenance')
        git_raw = self._artifact(catalog, MAINTENANCE_CONTROL / 'run', 'SOURCE_GIT_STATE.before.json',
                                'MAINTENANCE_GIT_BEFORE', MATERIALIZED_GIT_PIN)
        check(self.m.parse(git_raw) == materialized['current_git_state_after'], 'actual maintenance starts on materialized Git')
        final_git = self._artifact(catalog, MAINTENANCE_CONTROL / 'run', 'final.git-state.json',
                                  'MAINTENANCE_GIT_AFTER', MATERIALIZED_GIT_PIN)
        check(git_raw == final_git, 'complete maintenance original Git state retained')
        final = catalog['final.inventory.json.gz']
        check({key: final['raw_' + key] for key in ('bytes', 'sha256', 'git_blob')}
              == value['actual_final_source']['inventory'], 'pinned complete actual maintenance final inventory')
        return value


    @staticmethod
    def _check_maintenance(value, materialized, original_cfg, inputs):
        check(value['format'] == 'hepta-original-scoped-maintenance-result-v1'
              and value['status'] == 'MAINTENANCE_COMMANDS_COMPLETED_REVIEW_REQUIRED'
              and value['source_repo'] == CURRENT_REPO and value['source_commit'] == MATERIALIZED_SUBJECT['commit']
              and value['source_tree'] == MATERIALIZED_SUBJECT['tree'] and value['parents'] == MATERIALIZED_SUBJECT['parents'],
              'actual maintenance source identity')
        check(value['source_initial_inventory'] == materialized['current_source_after']['inventory']
              and value['actual_materialization_job'] == ACTUAL_PROOFS['materialization']['job_id']
              and value['actual_materialization_result'] == ACTUAL_PROOFS['materialization']['result'],
              'actual 3bb to 41e link')
        for name, key in [('runtime', 'runtime'), ('archive', 'archive')]:
            check(value['actual_' + key + '_restoration_job'] == ACTUAL_PROOFS[name]['job_id']
                  and value['actual_' + key + '_restoration_result'] == ACTUAL_PROOFS[name]['result'],
                  'separate original ' + key + ' restoration proof')
        check(value['qualification'] is False and value['source_ref_updates'] is False
              and value['automatic_retry'] is False and value['test_commands_dispatched'] == 0
              and value['source_preflight_complete'] is True and value['git_metadata_unchanged'] is True
              and value['attempted_commands'] == ['fix', 'fmt'] and value['not_run_commands'] == [],
              'one actual original fix and fmt, no inferred test qualification')
        check(len(value['stages']) == 2, 'two original maintenance commands')
        require_stage(value['stages'][0], 'fix', FIX_ARGV, 7200)
        require_stage(value['stages'][1], 'fmt', FMT_ARGV, 900)
        audited(value, ['actual_complete_source_and_git', 'original_inputs'], 'two complete maintenance audits')
        audit = next(row for row in value['final_audits'] if row['check'] == 'original_inputs')
        check(audit['input_count'] == 24 and audit['unchanged'] is True and len(inputs) == 24,
              'all actual maintenance inputs unchanged')
        for name in ('MAINTENANCE_41E_DRIVER', 'MAINTENANCE_41E_CONFIG'):
            spec = FIXED_INPUTS[name]
            check(inputs[spec['path']] == spec['pin'], 'exact original maintenance control input')
        check(original_cfg['source_inventory'] == materialized['current_source_after']['inventory']
              and original_cfg['materialization']['result'] == ACTUAL_PROOFS['materialization']['result']
              and original_cfg['runtime_restoration'] == RUNTIME_GUARD['runtime_restoration'],
              'complete original maintenance control provenance')
        complete = value['actual_final_source']
        check(complete['complete'] is True and complete['inventory'] == MAINTENANCE_FINAL_PIN
              and complete['postimages']['all_actual_physical_leaf_count'] == 15243
              and complete['postimages']['all_actual_physical_tree'] == MAINTENANCE_TREE,
              'actual maintained complete dirty source endpoint')


    def _validate_final_format(self, maintenance):
        value = self._observed_known('final_format', self.cfg['final_format'], 'FINAL_FORMAT')
        self._fixed('FINAL_FORMAT_DRIVER')
        control = self._fixed_json('FINAL_FORMAT_CONFIG')
        catalog = artifact_catalog(self._fixed_json('FINAL_FORMAT_ARTIFACTS'), True)
        self._check_final_format(value, maintenance, control)
        root = FINAL_FORMAT_CONTROL / 'run'
        inputs = self.m.parse(self._artifact(catalog, root, 'INPUT_IDENTITIES.json', 'FINAL_FORMAT_INPUTS'))
        check(len(inputs) == 28, 'complete original final-format input map')
        for name in ('FINAL_FORMAT_DRIVER', 'FINAL_FORMAT_CONFIG'):
            spec = FIXED_INPUTS[name]
            check(inputs[spec['path']] == spec['pin'], 'exact original final-format control input')
        before = catalog['SOURCE.before.inventory.json.gz']
        check({key: before['raw_' + key] for key in ('bytes', 'sha256', 'git_blob')}
              == maintenance['actual_final_source']['inventory'],
              'pinned actual 50f before bytes identify the complete actual 41e final bytes')
        meta_before = self._artifact(catalog, root, 'SOURCE_GIT_METADATA.before.json.gz',
                                     'FINAL_FORMAT_METADATA_BEFORE', MAINTENANCE_METADATA_PIN)
        meta_after = self._artifact(catalog, root, 'SOURCE_GIT_METADATA.after.json.gz',
                                    'FINAL_FORMAT_METADATA_AFTER', MAINTENANCE_METADATA_PIN)
        check(meta_before == meta_after, 'complete actual final-format Git metadata unchanged')
        self.final_format_git_raw = self._artifact(catalog, root, 'final.git-state.json',
                                                  'FINAL_FORMAT_GIT', MATERIALIZED_GIT_PIN)
        check(self.m.parse(self.final_format_git_raw) == self.materialized['current_git_state_after'],
              'Git unchanged across actual maintenance and final-format source changes')
        final_raw = self._artifact(catalog, root, 'final.inventory.json.gz', 'FINAL_FORMAT_SOURCE_AFTER', FINAL_FORMAT_PIN)
        empty = self.m.parse(self._artifact(catalog, root, 'fmt.after.postimages.json.gz', 'FINAL_FORMAT_EMPTY_TRANSITION'))
        check(empty['changes'] == [], 'complete actual formatter transition has no new changes')
        return value, final_raw, meta_after


    @staticmethod
    def _check_final_format(value, maintenance, control):
        check(value['format'] == 'hepta-reviewed-nonrust-final-format-result-v1'
              and value['status'] == 'APPLIED_AND_FORMATTED_REVIEW_REQUIRED'
              and value['source_repo'] == CURRENT_REPO and value['source_commit'] == MATERIALIZED_SUBJECT['commit']
              and value['source_tree'] == MATERIALIZED_SUBJECT['tree'] and value['parents'] == MATERIALIZED_SUBJECT['parents'],
              'actual final-format producer identity')
        check(value['actual_maintenance_job'] == ACTUAL_PROOFS['maintenance']['job_id']
              and value['actual_maintenance_result'] == ACTUAL_PROOFS['maintenance']['result']
              and value['baseline_inventory'] == maintenance['actual_final_source']['inventory']
              and value['baseline_physical_tree'] == maintenance['actual_final_source']['postimages']['all_actual_physical_tree'],
              'actual maintained source to final-format before identity')
        check(value['qualification'] is False and value['fix_dispatched'] is False
              and value['test_commands_dispatched'] == 0 and value['source_ref_updates'] is False
              and value['automatic_retry'] is False and value['attempted_commands'] == ['fmt']
              and value['not_run_commands'] == [] and value['nonrust_application_complete'] is True
              and value['git_metadata_unchanged'] is True and value['formatter_changed_paths'] == [],
              'one actual final original fmt, exactly reviewed non-Rust application')
        check(value['applied_paths'] == FINAL_NONRUST_PATHS == control['allowed_paths']
              and value['application']['complete'] is True and value['application']['inventory'] == FINAL_FORMAT_PIN,
              'all four actual non-Rust application paths')
        check(len(value['stages']) == 1, 'one final formatter stage')
        require_stage(value['stages'][0], 'fmt', FMT_ARGV, 900)
        audited(value, ['actual_complete_source_and_git', 'original_inputs', 'same_source_coordination_lock'],
                'all actual final-format audits')
        audit = next(row for row in value['final_audits'] if row['check'] == 'original_inputs')
        check(audit['input_count'] == 28 and audit['unchanged'] is True, '28 actual final-format inputs unchanged')
        complete = value['actual_final_source']
        check(complete['complete'] is True and complete['inventory'] == FINAL_FORMAT_PIN
              and complete['postimages']['all_actual_physical_tree'] == FINAL_SUBJECT['tree']
              and complete['postimages']['all_actual_physical_leaf_count'] == 15243
              and complete['postimages']['paths'] == FINAL_NONRUST_PATHS, 'actual final physical source is complete')


    def _validate_canonical(self, aligned, final_format, final_raw, final_metadata, clean):
        cfg, m = self.cfg, self.m
        proof = cfg['canonical_alignment']
        self._read_historical('canonical.driver', CANONICAL_CONTROL / 'driver.py', CANONICAL_DRIVER_PIN)
        control = self.read_historical('canonical.config', CANONICAL_CONTROL / 'APPROVED_CONFIG.json', proof['approved_config'], 'CANONICAL_CONFIG.original.json')
        self._read_historical('canonical.packet', CANONICAL_CONTROL / 'CANONICAL_PACKET.json', proof['canonical_packet'])
        artifacts = self.read_historical('canonical.artifacts', CANONICAL_CONTROL / 'run' / 'ARTIFACTS.json', proof['artifacts'], 'CANONICAL_ARTIFACTS.original.json')
        catalog = artifact_catalog(artifacts, False)
        check(artifacts == aligned['artifacts'] + [dict(proof['result'], name='RESULT.json')],
              'original canonical artifact ordering includes RESULT only after its retained list')
        self._check_canonical(aligned, final_format, cfg, control)
        root = CANONICAL_CONTROL / 'run'
        before_metadata = self._artifact(catalog, root, 'GIT_METADATA.before.json.gz',
                                         'CANONICAL_METADATA_BEFORE', proof['before_git_metadata_raw'])
        check(canonical_to_v5_projection(m.parse(before_metadata)) == final_metadata,
              'complete actual canonical-before metadata projected to actual final-format V5 bytes')
        after_metadata = self._artifact(catalog, root, 'GIT_METADATA.final.json.gz',
                                        'CANONICAL_METADATA_AFTER', proof['final_git_metadata_raw'])
        self.initial_metadata = m.parse(after_metadata)
        self.initial_metadata_v5 = canonical_to_v5_projection(self.initial_metadata)
        changes = m.parse(self._artifact(catalog, root, 'GIT_METADATA.allowed-actual-delta.json',
                                         'CANONICAL_METADATA_DELTA', proof['allowed_metadata_delta']))
        old = {row['path']: row for row in m.parse(before_metadata)['files']}
        new = {row['path']: row for row in self.initial_metadata['files']}
        calculated = [{'path': path, 'before': old.get(path), 'after': new.get(path)}
                      for path in sorted(set(old) | set(new)) if old.get(path) != new.get(path)]
        check(changes == calculated == aligned['git_metadata_actual_changes'], 'complete actual canonical metadata delta')
        recorded_clean = catalog['SOURCE.final.inventory.json.gz']
        check({key: recorded_clean['raw_' + key] for key in ('bytes', 'sha256', 'git_blob')}
              == cfg['full_physical_inventory'], 'complete canonical output catalog is the pinned current inventory')
        check(physical_projection(m.parse(final_raw)) == physical_projection(clean),
              'actual final-format to canonical preserves every complete physical leaf field')
        check(clean['source'] == {'head': cfg['source'], 'tree': cfg['tree'], 'status': ''}
              and all(row['matches_index'] is True for row in clean['files']), 'actual canonical complete clean inventory')
        index_raw = self._artifact(catalog, root, 'INDEX.final.raw.gz', 'CANONICAL_INDEX_RAW', proof['final_index_raw'])
        audit = m.parse(self._artifact(catalog, root, 'INDEX.final.audit.json.gz',
                                       'CANONICAL_INDEX_AUDIT', proof['final_index_audit']))
        self._artifact(catalog, root, 'INDEX.complete-entry-delta.json.gz',
                       'CANONICAL_INDEX_ENTRY_DELTA', proof['complete_entry_delta'])
        state_raw = self._artifact(catalog, root, 'GIT_STATE.final.json', 'CANONICAL_FINAL_GIT_STATE')
        check(m.parse(state_raw) == aligned['after']['git_state'] == cfg['current_final_git_state'],
              'actual final canonical Git state record')
        check(identity(index_raw)['bytes'] == aligned['after']['git_state']['index_bytes']
              and identity(index_raw)['sha256'] == aligned['after']['git_state']['index_sha256'],
              'actual original final index is the current canonical index')
        m.read_input(Path(CURRENT_REPO) / '.git' / 'index', proof['final_index_raw'])
        self._validate_index_audit(audit, clean)
        commands = self.read_historical('canonical.commands', root / 'COMMANDS.json', proof['commands'], 'CANONICAL_COMMANDS.original.json')
        progress = self.read_historical('canonical.progress', root / 'MUTATION_PROGRESS.json', proof['progress'], 'CANONICAL_PROGRESS.original.json')
        check(commands == aligned['commands'] and progress == aligned['mutation_intents'],
              'all original canonical command and mutation records retained')
        original_inputs = self.read_historical('canonical.inputs', root / 'INPUTS.final.json', proof['inputs'], 'CANONICAL_INPUTS.original.json')
        for path, expected in [(CANONICAL_CONTROL / 'driver.py', CANONICAL_DRIVER_PIN),
                               (CANONICAL_CONTROL / 'APPROVED_CONFIG.json', proof['approved_config']),
                               (CANONICAL_CONTROL / 'CANONICAL_PACKET.json', proof['canonical_packet'])]:
            check(original_inputs[str(path)] == expected, 'canonical consumed the exact reviewed original control')
        # Some original probes explicitly allow a nonzero status. Preserve their
        # exact records and producer decisions; do not convert them into retries.
        m.jwrite('HISTORICAL_TO_CURRENT_SOURCE_CHAIN.json', {
            'historical_source_repo': HISTORICAL_REPO, 'provenance_donor_repo': DONOR_REPO,
            'current_source_repo': CURRENT_REPO, 'materialized_subject': MATERIALIZED_SUBJECT,
            'actual_materialization': cfg['isolated_materialization'], 'actual_maintenance': cfg['actual_maintenance'],
            'actual_final_format': cfg['final_format'], 'actual_canonical_alignment': proof,
            'final_subject': FINAL_SUBJECT, 'qualification': False,
            'scope': 'Four distinct actual operations; history is retained and the current baseline comes only from canonical alignment.'})


    @staticmethod
    def _check_canonical(aligned, final_format, cfg, control):
        check(aligned['format'] == 'hepta-final-canonical-alignment-result-v1'
              and aligned['status'] == 'CANONICAL_SOURCE_ALIGNED_CLEAN_ONLY'
              and aligned['source_repo'] == CURRENT_REPO and aligned['physical_source_writes_dispatched'] == 0
              and aligned['cargo_or_formatter_started'] is False and aligned['test_commands_dispatched'] == 0
              and aligned['source_branch_refs_updated'] is False and aligned['remote_ref_updates'] is False
              and aligned['automatic_retry'] is False, 'actual clean canonical alignment only')
        audited(aligned, ['source', 'git', 'inputs'], 'complete actual canonical audits')
        before, after = aligned['before'], aligned['after']
        check({key: before[key] for key in ('commit', 'tree', 'parents')} == MATERIALIZED_SUBJECT
              and pin_fields(before['inventory']) == final_format['actual_final_source']['inventory']
              and before['git_state'] == MATERIALIZED_GIT_STATE, 'actual final-format to canonical starting point')
        check({key: after[key] for key in ('commit', 'tree', 'parents')} == FINAL_SUBJECT
              and pin_fields(after['inventory']) == cfg['full_physical_inventory']
              and after['inventory']['tracked_entries'] == after['inventory']['filesystem_entries'] == 15243
              and after['git_state'] == cfg['current_final_git_state'], 'actual canonical endpoint identity')
        check(all(aligned['actual'][key] is True for key in ('physical_bytes_unchanged', 'physical_modes_unchanged',
              'complete_source_clean', 'detached', 'index_equals_tree', 'normal_stat_refresh_verified')),
              'actual physical preservation and normal canonical index')
        check(aligned['final_format'] == {'job_id': ACTUAL_PROOFS['final_format']['job_id'],
              'result': ACTUAL_PROOFS['final_format']['result'], 'supervisor': ACTUAL_PROOFS['final_format']['supervisor'],
              'git_state': MATERIALIZED_GIT_PIN}, 'canonical refers to the exact actual final formatter')
        check(control['format'] == 'hepta-final-canonical-alignment-config-v1'
              and control['root_execution_approved'] is True and control['source_repo'] == CURRENT_REPO
              and control['before_commit'] == before['commit'] and control['before_tree'] == before['tree']
              and control['before_parents'] == before['parents'] and pin_fields(control['before_inventory']) == FINAL_FORMAT_PIN
              and control['after_commit'] == after['commit'] and control['after_tree'] == after['tree']
              and control['after_parents'] == after['parents']
              and pin_fields(control['after_inventory']) == cfg['full_physical_inventory']
              and control['expected_before_git_state'] == before['git_state']
              and control['canonical_packet'] == cfg['canonical_alignment']['canonical_packet']
              and control['complete_leaf_count'] == 15243 and control['action_seconds'] == 600
              and control['record_seconds'] == 180 and control['outer_seconds'] == 900,
              'exact original canonical control and budgets')


    @staticmethod
    def _validate_index_audit(audit, clean):
        check(audit['entry_count'] == 15243 and audit['all_entries_equal_canonical_tree'] is True
              and audit['all_stat_fields_match_actual_files'] is True
              and [row['name'] for row in audit['extensions']] == ['TREE'], 'actual complete canonical index audit')
        entries = audit['entries']
        rows = {row['path']: row for row in clean['files']}
        check(len(entries) == len(rows) == 15243
              and [row['path'] for row in entries] == sorted(rows, key=os.fsencode), 'all original index entries exactly once')
        for entry in entries:
            path = entry['path']; row = rows[path]
            check(entry['mode'] == row['index_mode'] and entry['sha'] == row['index_blob'] == row['working_blob']
                  and entry['flags'] == min(len(os.fsencode(path)), 0xfff), 'normal original canonical index logical entry')
            observed = (Path(CURRENT_REPO) / path).lstat()
            exact = [observed.st_ctime_ns // 1000000000, observed.st_ctime_ns % 1000000000,
                     observed.st_mtime_ns // 1000000000, observed.st_mtime_ns % 1000000000,
                     observed.st_dev & 0xffffffff, observed.st_ino & 0xffffffff, int(entry['mode'], 8),
                     observed.st_uid, observed.st_gid, observed.st_size & 0xffffffff]
            check(entry['stat'] == exact, 'actual canonical index full stat and ownership still current: ' + path)


    def _require_live_metadata(self, name):
        check(self.initial_metadata is not None, 'actual complete canonical metadata required')
        live = stable_canonical_metadata(Path(CURRENT_REPO) / '.git')
        raw = (json.dumps(live, sort_keys=True, separators=(',', ':')) + '\n').encode()
        self.m.gzrecord(name + '.canonical.json.gz', raw)
        if live != self.initial_metadata:
            raise SourceChanged('complete canonical Git metadata including uid/gid changed')
        projected = canonical_to_v5_projection(live)
        original_v5 = self.m.metadata_inventory(Path(CURRENT_REPO) / '.git')
        self.m.gzrecord(name + '.original-v5.json.gz', original_v5)
        if projected != self.initial_metadata_v5 or original_v5 != projected:
            raise SourceChanged('complete stable canonical metadata does not equal the original V5 DFS observation')


    def _validate_source_controls(self, plan, inventory):
        originals = plan['unchanged_original_controls']['reviewed_source_pins']['files']
        check(len(originals) == 12 and len({row['path'] for row in originals}) == 12,
              'all twelve original plan source pins remain present')
        rows = {row['path']: row for row in inventory['files']}
        applied, originals_seen = [], []
        workflow_raw = None
        for item in originals:
            expected = pin_fields(item)
            originals_seen.append(item)
            if item['path'] == WORKFLOW_OVERRIDE_READY['path']:
                check(expected == WORKFLOW_OVERRIDE_READY['original_plan_pin'], 'the single historical workflow pin')
                expected = WORKFLOW_OVERRIDE_READY['reviewed_current_pin']
                applied.append(item['path'])
            raw = self.m.read_input(Path(CURRENT_REPO) / item['path'], expected)
            row = rows[item['path']]
            check(row['bytes'] == expected['bytes'] and row['sha256'] == expected['sha256']
                  and row['working_blob'] == row['index_blob'] == expected['git_blob']
                  and row['stable'] is True and row['matches_index'] is True,
                  'current control exact bytes also occur in the complete canonical inventory')
            if item['path'] == WORKFLOW_OVERRIDE_READY['path']:
                workflow_raw = raw
        check(applied == [WORKFLOW_OVERRIDE_READY['path']], 'one explicit override; eleven original pins unchanged')
        marker = '          cat > "$RUNNER_TEMP/daemon-learning-driver.py" <<\'PY\'\n'
        text = workflow_raw.decode('utf-8')
        check(text.count(marker) == 1 and '          PY\n' in text.split(marker, 1)[1], 'original embedded workflow driver')
        driver = textwrap.dedent(text.split(marker, 1)[1].split('          PY\n', 1)[0])
        constants = {}
        for node in ast.parse(driver).body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                name = getattr(node.targets[0], 'id', None)
                if name in ('parents', 'packages'):
                    check(name not in constants, 'one original workflow constant')
                    constants[name] = ast.literal_eval(node.value)
        check(set(constants) == {'parents', 'packages'} and constants['packages'] == ORIGINAL_ORDINARY_PACKAGES
              and len(constants['parents']) == 48
              and len(set(constants['parents'])) == 48
              and all(isinstance(name, str) and name for name in constants['parents']),
              'exact forty-eight original-AST Root parents and unchanged ordinary packages')
        self.m.jwrite('SOURCE_CONTROL_PIN_BINDINGS.json', {
            'original_plan': PLAN_PIN, 'all_original_rows': originals_seen,
            'explicit_overrides': [WORKFLOW_OVERRIDE_READY], 'unchanged_original_pins': 11,
            'actual_workflow': WORKFLOW_OVERRIDE_READY['reviewed_current_pin'],
            'actual_root_parents': constants['parents'], 'actual_packages': constants['packages'],
            'original_driver_and_filters_unchanged': True, 'test_execution_observed': False})



    @staticmethod
    def _require_transport_bindings(cfg):
        check(cfg.get('historical_runtime_guard_path') == HISTORY_RUNTIME_GUARD_PATH
              and cfg.get('historical_runtime_guard_pin') == HISTORY_RUNTIME_GUARD_PIN,
              'one explicitly reviewed historical-only V5 successor')
        spec = cfg.get('history_transport')
        check(isinstance(spec, dict) and set(spec) == {
            'control', 'manifest_path', 'manifest', 'staging_result_path', 'staging_result',
            'staging_supervisor_path', 'staging_supervisor', 'staging_job_id', 'staging_payload'},
              'complete closed history transport binding schema')
        check(spec['control'] == HISTORY_TRANSPORT_CONTROL
              and spec['manifest_path'] == HISTORY_MANIFEST_PATH
              and spec['manifest'] == HISTORY_MANIFEST_PIN
              and spec['staging_result_path'] == HISTORY_TRANSPORT_CONTROL + '/STAGING_READBACK.json'
              and spec['staging_supervisor_path'] == SOURCE_TRANSPORT_CONTROL + '/TRANSPORT_SUPERVISOR.original.json',
              'only the fixed new transport and source-control paths')
        for name in ('staging_result', 'staging_supervisor', 'staging_payload'):
            exact_pin(spec[name], 'actual complete transport ' + name + ' remains required')
        check(isinstance(spec['staging_job_id'], str) and bool(spec['staging_job_id']),
              'actual successful transport job remains required')

    @staticmethod
    def _transport_stat(info):
        return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
                info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def _read_transport_file(self, path, expected, maximum=40000000):
        path = Path(path)
        allowed = {HISTORY_MANIFEST_PATH} | {
            HISTORY_TRANSPORT_CONTROL + '/originals/' + role + '.original' for role in HISTORY_ROLES}
        check(str(path) in allowed, 'closed historical transport file; no live-path resolver')
        check(type(maximum) is int and 0 <= maximum <= 40000000, 'original bounded input limit')
        self.m.real_directory(HISTORY_TRANSPORT_CONTROL)
        self.m.real_directory(path.parent)
        for directory in {Path(HISTORY_TRANSPORT_CONTROL), path.parent}:
            info = directory.lstat()
            check(stat.S_ISDIR(info.st_mode) and info.st_uid == 1000
                  and stat.S_IMODE(info.st_mode) == 0o700, 'owned private history transport directory')
        before = path.lstat()
        check(stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1
              and stat.S_IMODE(before.st_mode) == 0o600, 'owned single-link history transport file')
        raw = self.m.read_input(path, expected, maximum)
        stamp = self._transport_stat(before)
        check(stamp == self._transport_stat(path.lstat()),
              'full history transport ownership/stat stable during original full read')
        key = str(path)
        if key in self._transport_stats:
            check(self._transport_stats[key] == stamp, 'immutable transport metadata remains unchanged')
        else:
            self._transport_stats[key] = stamp
        return raw

    def _load_transport_manifest(self):
        raw = self._read_transport_file(HISTORY_MANIFEST_PATH, HISTORY_MANIFEST_PIN, 100000)
        manifest = self.m.parse(raw)
        check(manifest['format'] == 'hepta-closed-transported-originals-manifest-v1'
              and manifest['control'] == HISTORY_TRANSPORT_CONTROL
              and manifest['source_control'] == SOURCE_TRANSPORT_CONTROL
              and manifest['qualification'] is False and manifest['root_execution_approved'] is False
              and manifest['historical_original_count'] == 55 and manifest['raw_original_bytes'] == 7976106,
              'fixed history-only manifest; not an execution grant')
        rows = manifest['rows']
        check(isinstance(rows, list) and [row['role'] for row in rows] == HISTORY_ROLES,
              'exact complete ordered historical role closure')
        result = {}
        for row in rows:
            role, original = row['role'], row['original_path']
            exact_pin(row['pin'], 'exact historical original content')
            check(original.startswith(HISTORY_EVIDENCE_PARENT + '/')
                  and '/.git/' not in original and not original.endswith('.lock')
                  and row['transport_path'] == HISTORY_TRANSPORT_CONTROL + '/originals/' + role + '.original',
                  'fixed historical origin and isolated exact transport destination')
            result[role] = row
        check(len(result) == len({row['original_path'] for row in rows}) == 55,
              'unique historical role and origin; no wildcard or fallback')
        return result

    def _read_historical(self, role, original_path, expected, maximum=40000000):
        check(role in self._history_rows, 'explicit closed historical role')
        row = self._history_rows[role]
        check(str(original_path) == row['original_path'] and pin_fields(expected) == row['pin'],
              'historical provenance path and full original pin remain unchanged')
        return self._read_transport_file(row['transport_path'], expected, maximum)

    def read_historical(self, role, original_path, expected, name):
        raw = self._read_historical(role, original_path, expected)
        self.m.write(name, raw)
        return self.m.parse(raw)

    def _require_transport_staging(self):
        """A future actual normal stage and complete readback are mandatory, never inferred."""
        spec = self.cfg['history_transport']
        stage = self.read(spec['staging_result_path'], spec['staging_result'],
                          'TRANSPORT_STAGING.original.json')
        normal_raw = self.m.read_input(spec['staging_supervisor_path'], spec['staging_supervisor'])
        normal = self.m.parse_supervisor(normal_raw)
        check(normal['job_id'] == spec['staging_job_id'], 'actual successful transport job identity')
        self.m.write('TRANSPORT_SUPERVISOR.original.json', normal_raw)
        check(set(stage) == {'format', 'control', 'historical_original_count', 'manifest',
              'packet', 'compressed_packet', 'part_inputs', 'files', 'source_writes',
              'old_path_writes', 'main_dispatched', 'qualification', 'automatic_retry'}
              and stage['format'] == 'hepta-closed-history-transport-readback-v1'
              and stage['control'] == HISTORY_TRANSPORT_CONTROL
              and stage['historical_original_count'] == 55
              and stage['manifest'] == HISTORY_MANIFEST_PIN
              and stage['packet'] == HISTORY_PACKET_PIN
              and stage['compressed_packet'] == HISTORY_GZIP_PIN
              and stage['part_inputs'] == HISTORY_PART_INPUTS
              and all(stage[key] is False for key in ('source_writes', 'old_path_writes',
                                                     'main_dispatched', 'qualification', 'automatic_retry')),
              'complete original history transport receipt, no gate or source action')
        expected = {row['transport_path']: row['pin'] for row in self._history_rows.values()}
        expected.update({HISTORY_MANIFEST_PATH: HISTORY_MANIFEST_PIN,
                         HISTORY_RUNTIME_GUARD_PATH: HISTORY_RUNTIME_GUARD_PIN,
                         HISTORY_TRANSPORT_CONTROL + '/ACTUAL_TRANSPORT_BOOTSTRAP.py': HISTORY_STAGER_PIN,
                         HISTORY_TRANSPORT_CONTROL + '/ACTUAL_TRANSPORT_ARGV.json': HISTORY_STAGER_ARGV_PIN,
                         HISTORY_TRANSPORT_CONTROL + '/ACTUAL_TRANSPORT_PAYLOAD.json': spec['staging_payload']})
        rows = stage['files']
        check(isinstance(rows, list) and len(rows) == 60
              and all(set(row) == {'path', 'bytes', 'sha256', 'git_blob'} for row in rows)
              and len({row['path'] for row in rows}) == 60
              and {row['path']: pin_fields(row) for row in rows} == expected,
              'all 55 originals, manifest, historical guard and three exact staging controls fully read back')
        for row in self._history_rows.values():
            self._read_historical(row['role'], row['original_path'], row['pin'])
        self.m.read_input(HISTORY_RUNTIME_GUARD_PATH, HISTORY_RUNTIME_GUARD_PIN)
        for path, expected_pin in expected.items():
            if path not in {row['transport_path'] for row in self._history_rows.values()} | {HISTORY_MANIFEST_PATH, HISTORY_RUNTIME_GUARD_PATH}:
                self.m.read_input(path, expected_pin)
        self.m.jwrite('TRANSPORTED_ORIGINAL_PROVENANCE.json', {
            'format': 'hepta-closed-transported-original-provenance-v1',
            'manifest': HISTORY_MANIFEST_PIN, 'rows': list(self._history_rows.values()),
            'transport_stage_job': spec['staging_job_id'], 'transport_stage_result': spec['staging_result'],
            'all_55_complete_actual_transport_reads': True, 'origin_path_availability': 'Unknown',
            'old_paths_recreated': False, 'historical_stat_records_rewritten': False,
            'current_live_checks_replaced': False, 'qualification': False})

    def _verify_transport_stability(self):
        self._read_transport_file(HISTORY_MANIFEST_PATH, HISTORY_MANIFEST_PIN, 100000)
        for row in self._history_rows.values():
            self._read_historical(row['role'], row['original_path'], row['pin'])
        return {'historical_original_count': 55, 'complete_current_transport_bytes_and_metadata_stable': True,
                'original_location_availability': 'Unknown'}
