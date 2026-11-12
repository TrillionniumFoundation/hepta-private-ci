"""One exact full-source admission, clean maintenance, actual list and eleven cases.

No ordinary/Root qualification. Reuse the exact owned target, or create its
absent path under the existing owned parent. All
failing logs and source postimages remain in new, create-only evidence paths.
"""
import ast
import base64
import datetime
import gzip
import hashlib
import json
import os
import stat
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
import traceback
import urllib.parse
import xml.etree.ElementTree as ET

CONFIG = json.loads('{"admission_frozen":true,"maintenance_mode":"consume-external-clean-terminal","parent":"e403c45570ad313851ca71392625e5572882405f","prior_maintenance":{"expected_exit_code":0,"result":{"bytes":2870,"path":"/home/qian-qi/hepta-learn-037c-evidence/maintenance-a4a1b5eb6cb4-v1/result.json","sha256":"df3c3c2346180d1cd584a4e579337720b384cecd899fa802131281154122c140"},"source":"a4a1b5eb6cb45fc1182564e6b81026a2a2acf609","tree":"e09e7fb338e5f9a37fccfd4f05a8d5c222d7c0da"},"qa_fast_forward":{"base":"374aa919931e8ee5446b4ccdc49e651b7848cc5d","base_tree":"981c4675a6579dfd9748046d3d01a2268f11c36f","files":[{"after":{"blob":"0b645be03768d2c8dcd15e9b94bf75e64fa6c5ea","bytes":13482,"sha256":"973c2287d6c8a447c65f4b87a4e0921defb9338a9d62680daa693407e6f46266"},"base":{"blob":"4da0873c757803beb46256d84e27e63b12991347","bytes":12997,"sha256":"5a3a115cd814464248a0b00229d79c5bf65b85f8812fae3689a5134863ffd071"},"case_count":8,"component":"B","path":"qa/b4-no-bypass/test_original_evaluation_panel_source_closure.py"},{"after":{"blob":"efbf08c9dc423254d933669e414301689ab8e352","bytes":12700,"sha256":"4afd8ee94af50d88f0e1e0d02cee80e3aa430bf1b5309602016aa545a167b8d1"},"base":{"blob":"a65614c5bb04d3d22b007213a94c20f318bf73b4","bytes":12634,"sha256":"e61cb68bafc1b9e2d80f60e8c1800dd4e4dec5d10e5b9ee367da98ad31b45cf4"},"case_count":6,"component":"B","path":"qa/b4-no-bypass/test_original_qualification_owner_source_closure.py"},{"after":{"blob":"927b7de74c4a84faf3037d40a86c383cf0ac223e","bytes":13541,"sha256":"0ed97611cefb69835f6fb6e573a751a169f810fa9c2c9873cf7cabb7d21df96e"},"base":{"blob":"ba65f8cebf39277681b28812ea0a34c42c37ea8e","bytes":12582,"sha256":"1b9f8b9c9bfdc004521f7007efaf228a7fcb8819059679dd040ac060786af578"},"case_count":15,"component":"C","path":"qa/b4-no-bypass/test_original_learning_owner_source_closure.py"},{"after":{"blob":"4203887e7a6b43f6cf8fbbfbe27f46e689e15c46","bytes":11022,"sha256":"f09e819bbd565dd83dbcaa725df6e5dc9017d3d60ffb7fca19ae57de907ce218"},"base":{"blob":"6fc51eed804792d4f009697f76f2d3c20a5c9827","bytes":10167,"sha256":"d06d8d50b02fdb1ae5f5913348e6d9337c0e02515f7ad1e64dbdb1bed03e8039"},"case_count":6,"component":"C","path":"qa/b4-no-bypass/test_original_model_selection_source_closure.py"}]},"records_suffix":"diagnostic-eleven-v2","repo":"/home/qian-qi/hepta-learn-source-20261112-037c-a4a1b5eb","request_key":"learn-037c-native-a4a1b5eb6cb4-diagnostic-eleven-v2","required_names":["runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::evaluation_provider::panel_members::original_panel_reads_actual_b_and_retention_with_full_original_signatures","runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::selection_owner::published_read::command_owner::next_use_command::q24_next_use_command_readback_refuses_actual_publication_withdrawal","runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::deep_readonly::q24_deep_original_no_update_selection_c_and_cold_readback_preserve_sources","runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::deep_readonly::q24_deep_original_no_update_selection_c_hot_readback_preserves_sources","runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::evaluation_provider::panel_members::evaluation_host::fixture::training_read_support::tests::original_panel_training_proof_rejects_new_source_reentry_and_incomplete_slots","runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::evaluation_provider::panel_members::evaluation_host::fixture::training_read_support::tests::original_panel_same_call_training_keeps_four_execute_and_three_readback_frames","runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::evaluation_provider::panel_members::evaluation_host::fixture::training_read_support::tests::original_panel_last_actual_training_failure_never_returns_or_resigns_b","runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::evaluation_provider::panel_members::evaluation_host::fixture::training_read_support::tests::original_panel_last_training_slot_keeps_the_actual_cohort_tail","runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::evaluation_provider::panel_members::evaluation_host::fixture::training_read_support::tests::original_panel_cancel_keeps_the_held_lane_and_consumed_channel","runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::selection_owner::published_read::current_slots::published_current_last_original_slot_rejects_actual_withdrawal","runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::selection_owner::published_read::current_slots::published_current_call_rejects_other_original_incomplete_and_reuse"],"root_parent_count":33,"source":"a4a1b5eb6cb45fc1182564e6b81026a2a2acf609","source_admission_mode":"prepared-newcheckout","source_gate":{"execution":{"bytes":1483,"path":"/home/qian-qi/hepta-learn-037c-evidence/source-a4a1b5eb6cb4-v1/source-closure.json","sha256":"6d7ca8638ca69aeaf89833681cd672637a09c961d234d9d354b983a903a26c50"},"expected_cases":504,"repo":"/home/qian-qi/hepta-learn-source-20261112-037c-a4a1b5eb","result":{"bytes":1156,"path":"/home/qian-qi/hepta-learn-037c-evidence/source-a4a1b5eb6cb4-v1/result.json","sha256":"fd283e2847c6dde06ffb6f0a97bfeb2ab250e92f7ff1eb89d8b4dd9471cf3294"}},"tree":"e09e7fb338e5f9a37fccfd4f05a8d5c222d7c0da","workflow_blob":"0f4dffca6dcf24c197b9211e56af1cf80eb640da"}')
BUNDLED_DRIVERS = json.loads('{"diagnostic":{"blob":"7c706f1c4452d193095b939cd6c21461daa69c4a","bytes":17242,"gzip_base64":"H4sIAAAAAAACA908/XfbOHK/+6/guX0FmZVoO7cfrXLqe46jxLrNWq4j712eV8WjSMjimiK5BBnbm/P/3pkBQIKkZDvbba9X/xCR+BgMBvM9YPb39y+q1JFZVYRiuMyqNHLSoIw/CSdbSlF8gucslU65LrLqeg2/wilEnsm4zIp7Jp2siK/jNEicMssS6e/tzdexdKICIBROlAnppFnpXBdBWsLYCIYW985xlOXlwDnLLvMoKMUAepwoEJssPbjIYHghwgzm3+/9UgVJvIpDwsJ3pthVBjEhJJwgLKEfmn6phCxFjXkJb9IJYCswKi6cVRAnVSEAOwCQi2KVFRvEy8GHoDxYxXdOHkg1JRWIOexRBAjEyYssFNB3G5drp0pDUSACjiwBcX9vf39/by/e5FlROkFxnQeFFPW7LPdWRbZxcI9lvBGO7jDvAwf//TVL6ynXv8a5eV4Hcp3ES/P6s8xS85xJBTgPShxi4J7DqxlS1DBlFt6Isn6rlnpHdct9/ViKu/K2CGoU7jaJL8pCCH+SiI1Iyzk8w76cyXxvby8SK2cDtHC90Z4Df7T5whnXhPCPi+sKp51TjxsJGRZxjmc55jzKQs49a6YfRBEP9BSXDYfIaAyIdJ+LMe5tQEcdFyIaz4tKPDE3BHaTv3W6Egj2RVOquMQZ4TqLgb5jl0VxcJ1msozDoUiArVI28AYEYtvfF+wNZGQIffBq70/NgYESzkBPpR+cLF3VjTRVRyR9fIZ/ZJZ8Eq4sizgsrcU1BZvB9FqPV4NK6BMljEEE3Ez6Iv0UF1l6xU6OL97N+Bz+ncz5m+kFW3idufHKcQvhr6okASkM1y67Ohz+WzBcLT5/ffgAO6N11Ul4DmiVM5QUm2RZYbD0Y8kLkZD88zJzcWse9isEt3Z3QQH2MFRUceR6znjsHGq+tk5CFEVWuEwfFeqQlE7DKao0FcXAEXeglJwPp8f4WIoiJf2kCEkKidBhau1UiAjwwvmayMRDDqgXWAOagQYsSBI9HFt4FBf1ieC7YgNDTwsirubWUzT1cJuoj0070iVYwqFUpTmVLX9IZjNBref8QZ84O4CdM28npUidq13VRAucFfysHQAngFjhOk4iJ1s5CAqVS5vBW8zob25glqu6JDErEjqWJc9uxm+DRGrmhbMM1zi0OWnQcz4qTB/MByhx93AASlwNcA4cplSThL3QaNKva5GXAQ9jLu5EaLQsYIlrihBoxpPs+lpEW2b8XKVxaaaEWZLAVnvDuLKxouBk74Lr2kSANQIVzZW1ExE3ZrY/Y8/sV0ueX5FNdT/MLi9OJhxYcWzJ0cCZTz7MJ2967TvO/nRyPj/mJ1P+/vhsMmbaT1iLIALePP84P52dvZmdzf9yMZ1PXn+cT05mb2DYEdsFT2mFM1AJs7dv308RZgmHCKdME9CkXMel+8KoO2lxFhCjKlLLgsERi/CGZ1WZV6V7xWAmYNXMXYAyvo3GigVq+DIADZQGaH4/BQlou2YFsvGukdcDB0d5fpaL1GV3zEPmBJYRwWbU2h6aZj+qNrlLAAd6EPzCUfIbcW84NU4jwGv8si1parR/W4CUuOyn1CaGTINcrrPSTYKlSCxUETXUzUgtlsjhKk4EWjs2/BUQ/WpL+zADb6jQz+IuTKpIDMGNSaOgiMzMhtjZLYK/WtQtK1QDwS1qJ9yXiFwpSiIkMFGewHpL9tMhyI8zdD4vGXvw2lRC2QOIwKkrGQGJI+ECuA4piL9glJZKnNMagDoONQqN80nywbIpx61pB60m7zdJnN64HSTM1vwgh1ON3M8Ml2AjWglosImljNNraMATe+irxDBLyzit2nYIBC4wWxMpbS1DSxlEhIM2YR5ivwVDR4DaMh04iS/vwYXt6OMNQIU12NHLQ/hjj8Jye2izo8PD7775xp6GHqzrwQ8n0P/iHGZHR0cKAA7/9uuvWRuFRwkHMOANf+CNNgCvCUgOEucRtwc07zp4+c23MFp7vL5qUBP9tbiL4mvw6N1HgSyTbNkGcQT8iK0OA3FATV8j4/n6kLzdALf+feUQi8NvDzeLVRTwCA6rVgzSRdr1FYIUYMoCCKXQXRygEI7YNvRIMWFwoJRRo6GUXgCEmE+S7tOS1yDJAOtuqXSWUpBtQVBtWulojJv1SI/BBj6zMNtsQK2OlEIpxKchGXhE9XRy/IZ5vpZl5CSwoFtPiWEMsRPGf37G7odngkK2raQBpt9Ip4HhDMHHi9PxpyPVUqVlEUD0Eyk1OCZfql5lG3SlLhXj4pEhGeMUXHcMd/kuTjX0azFEDZ0MTnNOeELM2J7GbSpicO4thvmsjS03JgCxQiBg4V7Q5AdAbpVUcm057ZadpDHKktxmxc0qyW4bxcp8IN+6Wh6YLnlAPslQheHDRARFCopwqEJqH/QLa4HiaArG9Wtfb22C4oaiQWYpz6B0/t3Z/+eLy7OzyQWfT344P+guqFIHfn6/7/zpTz+x848/oUlUTo5xgnR6YVwHrHCmaFkbvWejabEVmSmF2cA58q6OFrrNQhJWxPOB3sOF114XlD8azBIt42d1wCvyqCNy2iHgVwGX28HU85dZdN8IICjhGMwMwgrBFyGdiZOPwfhcp8qcIQdij69CBkkhyVFbiNH4og8AXmIJCs4eDsgj66JhR8ff61lRnEqBhnamUWJyEBZwKcEJ7lvNPhGuEMYCoxFAHYgI7mjCBbCdQsRicL3EwDELoLHsw6tRWQx2dGv0FnX8iEZfz8IwBYmmXz2MUfAdvRTT1ov5cD5oBdc6DtjIhlw4jw4XX5FQZpWv6k3YUU8RxGA2f8QtT1TkA1ojSOKoSZDVQqjnU6pLRzng64UJWgJMthn/by2SHBw29MJYfl+us/SPeEg6UDnQMYRIEo4JL66Hg+RodaiW6bviDKXhbqjkPU5XohgibvCzzmSpfUUyD0OIoJgJk4zJYXoh5i2asBSIXOUcuFBs8pJsHwVjNGApgI7Ip3X8bhJyjYO5orM2qs6MbdzgEnainXa0SCAgKnkGeI6/A49o4GziNN5UG6KFHB+24gZZJQgTIjfbdJII1BrZayBv9wraC7TealyADsCvkRzrd88WeYVHW7IU31yAoYIJinMMWkQlEb1qOEgFncAijokL7VABwIOREjy7TeF01mg/7ai8XBO5yQtHvqYHVABKYQxMiD2oTYRik0IeqBEHKWY0ZMm2eE2wOwqtjUO+2Ov0yPa2rRgOD+WKySrKiPNQ9bJwDZug1ws2eNRHW7HPKm1DWZuHkX67pjcMBjdBjqmtgcLCw5AQg0ZtMmvi4cY0f9Xh44BYW2cVbHaiCH38FJ0OkiwMkgNKBPh3xn7WvIBAanp1mEJ1gmIAhLZx7BC8hawYEmgTykW0hqXhag1K2kHzNimTnysl5nSaJO4J5ogjLfqrFcQSohVJD552lCnnCm6bijYPFSzlng0x+ZkoAyMlex4wWYXIH1oT4WTSEQquViC9zobv/smZryGowtIAKHVwFj8JVTSopelkSsFcgbmZwhFBuAbCQ7um1CsLVJYm92AIpKk4IAGHSD0tNJhek1UOngSovjKjdao0XAfpNTTo7E9W+DXIBDNW10EpTOaUc/Q8Ofd8dPU5HTyjUSAfNBL1enO49nE2toGiHAPaGzhNDt1kurbHUK18uaXtFYg6F/5UvgjGItdsZbyWRkC56nsyqJ9cdn48P8UDbfJX+NZkrVTUYGWldvET25GeQgAqDTU9O7mY/DA5mx+/bxpfX07fv+F/nr3+sBOwGnh+MXs7fT/hiBp/M3l9+a4BYvreTH7sdlkZ8V3wLy4/zD/yH/+VH1+cnE5/JIzrtg8XJ/z19OzN9OwdN7R6P319AqQwDY+AvTzn89ns/cnp8fQMZyKkd5MzPvnr/AIoSkAAwQ8Nvlau7gmC4Mh30zl/O5mfnPK/TOenAHCKkNRJGGxPfjj+nvYEVJrPTp6AOp9c/MBPZu9nFzQXDvCv/GJyPuMXs9m8Y4t0ChRVFnroEGiPrMzoFbwvyPbBA5o+xXTAj/q9GfqwC6zJrircTmc/TMZW6hW0v8uaLi1MKOD+OgOJ9ijyCkGOMtDUT+pBfWBbV7H6dixTgJKq8uesg4d2Mjt7O30HP5dnc0rg2q3fTz7ywzGTwUr4KmuPxd8vgfvj8fvLCcB4XA/1M8+nMxCu40tgHxDhj/w/Lo/fT99OT47n09kZ/zA/nk+A5y9AhBVkU+6A/S/jFNyj32UZ0kS9BbRafO4SJ6eTk+/PZ9OzudIYyL49mOSb5FmcNoWIR5iQsgVJFkTS3eKfH8AM7dqq6ByDZdfrgFUpdPCeUPnu1/XlAZid/H4g7+UrqkVQY1MeG48PXzn7uze+r9IZqvxDhhKmjcEpsPIVjwOg9dE55Oi4uVi8AbH55OdZ7h55iB4ZyTHjHGvQnDNvv7Mzy0S23UsgDL3Eu1n4hYs6AVytMWb7VDpMaw6durHy4PbRYLgokco7Qdux3DBkg+YIwHZqpK+ORotFO4FU+35JgK6FSSOpDB1MYaMmMjIFyojjcUHPobG6Kr1rH+WD1w+UOu55DVe5zsoh9lWaCZ3fx037lrjETlVRHANrai/p0QBNOcZ1qNIa0/F+TYpjPHaYuXfCKLHSrDl2DkcdltFVuPEXFOD6yfbHt/Ak6vWRM7Nokx0jIg7N0g0TmFzhOoDTbtX7Xrwwox+8baUU03vFqHbN0UWv98YWW8on/ZC1prAu9SZBeCN1LRx3GTmEtxMGMLOG7XX55snjgenoJKKL607mOte2m6IojIAc6h+c2qWxPknSENjvYxItXl4xBMOUp0AYg6SrpQFPGgjBRuQyeRPnOcbgprq+2HKEVil7y7GJuxx4XkRUR9E5Mmbwgkbz2D86rXrMAMp26TaT7Hre0ZGK/vMlVqvr61oYF+ElJzpBCH1acVNz3cqk67ZkOdTVDHWSv0vGA1lDYakVxbY0SFlYSdY67VTXUE35WvW00VZtV6besUB6WnKE+zFDdM1h8eS+9HrIHkhVpKKSiRDkObUIqRf12hqfqeTxME6xUmN4Zq9dDdkp94wiv5EV+WGTCvJG7SCvDVJfUVFj1AvOVdebRtY9FQTYXEExQLU304VKqcWRvoyG1gcbKMxF4EZ/cGWubPvUgQPERybnAUIzF+n8NLt1zV06vypDEH2Zqdt9PQh1aWBXNceuHTxSf2SqNKJT/DuhdcJ7u07yGHAjW7ZiqPPfozoH3ZnVui/JwySINzDYuojmqItoQ9JrmNZ4Vd+DTOAnrKSIBs1FTeB60g8tuB2viVnuDyzWjbooXIE2z468thSo+9Gx0w6lOiHPlnB2F1A7pH809t8W0u89Ef63QvwvjNz7sDuR/CMBuvfQTLfMg8qUM7yNG65BOQKMq67H2Vl2v3c19JVxJeX46ophIAmz2HAIfC6JAdTzMgOjuhh03fh90KIU4tpTFgOTd+w0mqEmu9zqX7zqA+86pwMroatsNhlsvYHF/mLgHL087FFIRUnDZRUnmPjUQdPA+eO3hzsHA161FBgrAvR9UU9WuMer+yHKFusurcbxdprit0VxTZq3d/Orv0rL0lkXDdE57l9Sbds1UFylqUIVyrqNRlT1GI3CuAgBEC8DecPBPQXbD62/vPya6wF4HSThUmiDrWKA0cjY99EIy4WV0lZwqJ/iCLvzIIVZG7FZwsLNaK7akQqSq0wsX3I4ZPTSYZcIhLKneKO0cdixpAoGu1CJ6S/eAvIlB7VYO/6AkAkBMOcLkjMa9XaYV0vwUtciInRhGcWOprsGqtvVit1WmrsETQ8PK2ivd03QtZLHHUdgqVRq/Pc/oUiInBBBjlZTqammb5pxxXgWlJCOBTw1aw85rI1k48pDkf+n0AX3sI+p/J9F9Tm8b41Bh2k0WsV3yMuABjicGBIS2g0n6sU7MlMPhoWyFUz5GZCSwHC3eovQBBIEDhieWwxR/SZPBNIoycp//O1L8DN5GCQWIW6AKSRfwea5ucuLWy/XQIiGE1YFpoj/4fefBLI0uqOeqGtonD544SqbI0FO4BFVpuTL/x/7rmcgL+tzh1DM0CPM1ngpDwLJ5B9+vyFeYEmsPYIrEAEVUqH1cSqrDdgkrEymIvl72sOqwKhG6Re723TQ0TU2PCH9rLSWPrj/puH7X9oHaR2DOd3AbnZl6Vll7Sv0p1veF91L2PYhEXhjw5zuSliXecBXTUtVxu/1xWkpkgSCTWCRIfLbU/UbvBYQkw4YUhzj/A3TmFmcqoyaS5lxk7rxmLoJp2+VaafRe3oJBDVErRtQ8Zm9ZItd3irdVqtzuebTmNEWelmDrl7UobK9oyfXbb6k6aR5tt92wuijnf3DIZ2aShO5qMLKrm/4dlZG9nP60KuuhlwdLbxXTq6/ikFNND7MvoP4ZTeEKzc/SL3+DHV8isam4K9qaIN2VWqxG3bvVs8mq1IV0SlImCDKD5rKmX5XpbqFHcg9QgKrsqS1JBWX2FcIzc4ceV8xoq7uyj27+rTf/QaD4jzK1tLRkYS1y0bdug2NG7SzXhDxfXvobWFJ/TnXE1Lb8CcQcAhWGCJM6qFw8jFp+g1CavLEj4PtScoRhrV0M6p97fiRUDlYgTZ4dqQs7kKgizOhH8r9Soc+J2sksf6iV3+NsGKf8TNIl4Z5PqfaIOcPI+czNT2w7k3rlU7fmU+VVeq5Gd+/Wk03jJL2Ld5t2qCjkOyU9HNKYnaO//FbciRdJJbU9stzLlY5zvY6+cKu520pvfRKhO0P4Hq4VVr0dy03+KIvL6y0CElolRJ4HxZn/buXXQHcUpAxAHRSXe1q+6y6pHHFGgptq4vt4k2lqnDfjl62rnMY/WXVMVol/6cFYbdA0KpUaKhyYOtni0ePYXtXc3v1FCXevRKVLsD8YdwB8TT2pnBCeXJMQsd4uz8u7x1zpy6qQIqvt/1XBRYez6Rfn3ZvqfhU4/sF1GsVbhTffHnlZmupxWAJ7eZxsBWizkuONP0HdYc6plHnNDpAoFM5sL+9wFJ/ocMUn9NHZ/WVb/V9GVaZ0bL9fcsXD+bjYvpgBs3CMssS1+DqeXt7e4C7OXHKl9b3TRQTqbLfh3sJ2n9yR1+X4P+I4O39F/henjhaQwAA","sha256":"90acc3ef56963a9a6a933d814a719e7f65188030a2ce91feb83ccdcbd18173f2"},"list_run_gate":{"blob":"139ae1c2e05b858d1a9fe00067eeb169c0565cfe","bytes":25288,"gzip_base64":"H4sIAAAAAAACA+08a3PbRpLf+Suw3g8AHJKW7CT2Msu7chxl13t+pGznaqsYHgoEhiIiEGAwgGXGq/9+/ZgXQICinORyubpUxSKAmZ7unp5+A/fu3Xua1E2ce3kmay8uUq+sssusgDs/NnCnFvDPdVZvvLIQ3jr7IFLv8cOzM+nFSSJ2dVwkwhNFOh2NLuJk4+02sRReJr0k3tVNBaNXe6/eCK8pkk1cXApngWfPvaQs6qrMc1F5jcyKS1glp/GjppA7UdReJfK4zt4Lr862omzqqfeq9HZxhc9kdglw5BgG1VUm4EdZ6XGe+FCLQmZlAahWYpThQmmTiHTqPbOrSlE3O5yW5CIu4Ge9iWsvqUophSTEmWYg0dvGV3xvdL0pcwFzf2oE0r+Os9wT70XhXW/gn7jwsiLN3mcpMtaQW4mkrFJPxnsJBAB8YNq9e/dG2XZXVsD76hLIkmK0rsotMAbQS2pCXw14VjZFLSp+nsa1QEr1Q309Jvp/hs3ScGFDNnm20pf8B25MmzrL9d0fZVno36XkJXZxjRP1Ct/BpR5SGeiyWe2qMhFSmjt78xNRAbn453cXz95dfBO9evry4q039xZ+BZTAs9kMxUvOZklWJU1WR3UsryIQgwrgzWY/Pfw8UgO2ZSrySArFk6i8LkQ1m2nezmbifZw3MT0DfID1+HgXFzBrK7YrUUk7OuL7lYhTGcUk/tEqAtmHWyAzBARFPlo3eR6ZWSRtKNPSH3t3J6EAgYwaKaJyJUX1ntBXvyLZ7JBhs9kBhbtmBSdzI1JCF5Ypt1vEVD02QNV9XrF7l+au4uQKfqzhvqGaoCexoTit4us4/yTybt2hVIgdIYJHnKfSLcPfooyaHcqxAyWhbYHD4NCwg7WRbZEsmyr5xN34rdDdlPUhpvK3RfUU2XfGbEoJkgZqDWUZ0KjirIB1CW0riWrxzpkxg2Ghcg1TfgSkJAjctSIRbsEJqva0b1kBArjLBfIoL+s/Pvky3sKhinOHEVcgFDJaA/GR+CCSBmhF0usNMMJKwrqCmX98+vNY1lp3mIlo/QAUCAGqMlChTVVIOCfwE1WmjFb/N+g2M1CW1b6DM6D5kZQbgAD0ZPkfnt4E3brcoXEjQAPn8Ezp40I2W7BJ6NLB+N/THjYVuoKsX9zH+gFtnbXhOeln1lpq436h4fsfooO0jsa8hD2pLFWOnmVrD+j4y9G3z1+8u3gDDpfv/cvzpz+WWRH4iHUw973PvAJUEvzxQ99bgwNMl1nhtd21cPT6zfO/PX/19EX07uLtu+jZ65cvn776Br24kQf/+RglIN8QLv6dTPIyuRIp/y7X6zwrBF3s8N8EpPzDZIORwyS+BMJgIAM6fA4uu8jz7BJ97AlKtoKfkUKZXMC/TKKGMEEkJqh6wbPDMQ95hgoP8OKM78gaPDk5yUFlEVT0xw0iE9kk6NFOIIzYNUTVGvnMU5W6O3w4Wo5ePO9jUQKufYkDUVQUmzDcOsKuIZZolp3ILk1QD8vwNpgkCRAnsP3buJ5jEEBkmC1/8/2r6NXFP2nnv37x+muUpXORfvkoXoknnz/88vHq0cOzZLVenZ0/fBQ/Povj5Isvzh6vP//iL1/4o9EoFWsI/DIIk+B0oOgGuzirZDgjxFBXCQD58YYuUQivxH7sZbXYoiTSWB6K/2VrfIwPaKJ9gP+BdoO48z/xwUVVlVXgp82OfFvh/ePt61cer48QZh5KP/wIDQQCuIBbS0AHl6cnbMr4oSKGzzEeSwhzZZCWCejBoh5DtLmjB4o0iOsAlwzdQwoiWdV4Z9O/TM/PHnnvQApegAS8bcA/r/aeTDZiGwPlRZI3KcbB20zClsBtOcUYUdFflBDAQZwsKe52lk+zpA4xjB0YMb0UdQC6DY6HBG0GZyFUkywbD1lYcOSNsoo4QSQJ8D0HiuKqH2oE6/2uuyidyQRjVz8MMTNAKEL0DtjqkQt31NL7q3d2d7RMnF2XNf6LiQu1LMFSSjnFc7mkOwgAtxIHwd0zI4VEXJSlY/6FImcxdZm4nKKwyCBsSWlnD2js8BbRY8sqEqye3bkLKzQcbxvvWNo1RVbkW8R/NvdyUTAqCweNpR2vTcTYI8jAksPRh9zo5wgOdxhCQoP3mAvgM5YVaEQrLauyzNswj3KDEMzB7ZaYilFHT0H11nl8yTxBasIWVDpxIAkWl3WW16Ka0AM/vIUsGuXQRdcMh+2NHyrh9wJfnW5Uy/qs++FdicT9BhKb4qoAv8JjbD1ebIhIwJtWW2iklt6fQK1rfA5RwBxdVoAK7EBxBNeQh5BYsnxKqgGSC7Ohy1PI0xrWc+lUclBWoBvjKsv3oISKIl7l4giV7snagTSgpcOBCs0es3qAHumNyqX0KitSQ+fqlBkrRHk/ydQ0fRKHZg5rBwUI03KoH2RdheEncxQlpym01fIUfx5gvg+DC1Hg6kPM1ap0Gu92okiDjz7xdaYUhK9phDtGlfbSa/7TG6RnLNo7tgSgxHnzmK6Wt0FllkXEMjPV5SMC1uI5876NcylumNY/e+82IHYZJ4GbHbBbxFs2LmPaJbxveEt69CuPYmBwHH5qskrw4Pn8/Hyq7eOAwQO5cPXxMeOnVb2r4yXoHHDkKiE4VY+Y3WYOka8SbWFVXi94/5ak5OEaNZTe46VGXaWfA5pIoqzvGN8H5RftiB2CVx3X6KhWc2QV0UtL4jSwE0kAqkROaXZksJDEd7Q8IKfDgvAZjN5VIKMaD9hoZKLFC2RAU6tkWN6EoesC2sm8QQjCpQxl3niGzgANNmwLqm8iN9ociiTNvH4RQV+fjOzM7EwHpvgAli4yaBAZMPpd1QgVb2D0n0lejQIeLfHKuQUbom23oltXFab4SBcWpk2dhNNMlhw2BKGaDtZHRFtRxwEeLQWI5BGvpyWoCnBBV6AGQffwcXIkQjN6ta8Jb5qDdiUI4U8ks5/F4Wn35SZ++MWXMFxVOaaERApBEGwwrzE2o8LpRnxQz0JNtEoCIH90ujwAgSnRjlfAyrKCiEQU70Hhxu+Fde+/l6JT18JZMsMJ3kbkO1H5UjsfMgHq0wkyB1gae6lIMixNTUej16rgJXWl6bKKd5vJGg8zxI0kClTB8lQyAQtY72BhA4yKbRhhypFOA9jTL+sUAtWxUUyYuqmrJiEwr9me7r11nOeYp4QB2xhsDxW5MNnpqZCVy4OKP1zlaikZJlgrPgk/ZJmjs62xnI6e5rl3XVZXiC8skaXMP1pFfNAOLJrjKMkol+oB5gB01aRg/7hWhsxHyQDFhez2HsDmJlW2q+UD8AgmCtvpbs8KgfgzZ1mivBdJV8Bne5WXK3ioJQeE5DxY+XSXXOa6CvAMI4wwnEJUDQ5DEMKTlf/DGY6gJ65MaVVJMED7DcbRXU34hpNOShfaiqElyW434AWn8nLvKbn7yuX6+0xcKwUv93KagusWXVdogpFypAAoRpXAQ0B9YcDbKglO8W6EFcCIDlNecoHI4hWxOEcKtUijBr4snXyCvS3TJheH0Pk+w8eVAvwnNOhM8zJORTXF/Y94bMB/eIw9EnPPzbYsHs3YUumjhXkFi7E6kDO4p50B2F7Cduzdv99RXaAycAthFP656dE7BrDBBwab3z0TMEGo2GbYNVNMmvY8DCwwI+nssVbgZ9+4CQFN8aJ3EcfptgN7lJ6/7HDUTEO9B/GKAjjR8jfldJGBGnZ1+QEwrT6wAmxyYo7w+JNJUU5SsZMq00b2ZQKKC+HPz4fzZbz1rOsipR+M+ibW4XJG/zLqeo6oqlPm8MhpFV+DjF7y7DxG9U+iptk402Sixb5OlaQdbiGapTpGdR7FaPbJ+HYFxycNGLEG5NQxDPVJZzq619WZ1JyB3InTNMNzi/4Ft0TA1Fdgv2+sYXY4puzzB2Of2W44/DkcAU+sdKk2AG/u9ARMv6M5hiPAkPkBK8i8ztnE0qrz9uJz/uOkLojrECJkLLV6sZ0TVbHQtrdwwhO14PKVBctBrAPvOs60UrfiNV3njdwE4VcKO31thpVyupb7AhSbGg+6pSiDEGa4j2iqfkSTuXyoVNf9+4wep5e5FODIiefzIUMmkogh6j3RkD7piiQQkayOHGdXeYe2DSe6yvJcO4Z9AJkqGGF1piNFLNZIXHeEliKlu3r3x3BAb5G5YUyrym2cZj9ZF7J3ZA0oJvDZbNbg66DjFl+rzX2gcFcmTM+YU38MmSbpUss+RQ1mELeEc6ERZa2jTVlezVupb4aJHpCE2BYtI3bUBHqRhW8eRVVZ1jr3BjSbB1PlVqFnmyX1HHePwqwe/dI79jjfOnxKUMtQJxA4rNl6LajnyjDXYOV3KMPy4Dq7BAItsYDalG8/0D5aXW5zvxWKfhwIRS2LVFIAc1bAFxpOOgCzkaLu5aUqjQI7jdEMgi6uEM2QswPuHRqoSkyliKtkE1T+D6vg32cVGqV/4T/hD/L+DwGI5gEIRxbCTrqEszrgYweKAESYqUYynZvKIVBGXJNrnYHQTflYe9prt6251+49acsD60GeuyFnorbJIJViR1SN7qYACKypQDf0obG47yJCFrp9wn1KW7UUxrIHX+u8kGl1PLa2qnEdN/fJzeg0d0f9Ht3Zy1Eejp4/GiU5xNMQTzFTvyZ7ffFhB+5EGriHTO0eRt+6osRtM5rNdJLVKHx8CSboPlWgZHgQLTuGlnYn4ppksPBhmnGoyh27AeQ5oblV8JbWHofTVHB4M0V1sQs62Q9GEvYA0QHT835CrYq4xN8vnn5D3gwE28Mj/usjPr7xu4kQlThW09QVIQ5BQyJyUNDz98rxAzZWMfp+E9x1OQeh9k0Yj9sX4V4FTtjO6Uii1k1HBK6bR9lN7dr05yZI+afNdhcQqLGnEwsSGz6uxF7O2Y5mBe7i/KHrM+DIKYVggf9D4etkCYR26LJRu+xhvoH5jVIXp+jgorOyErljEEnQe+yzcbW24DVsmy13KWAMIZtc15P+TAmEbmctBua6/dbT7bewi6Dz1+1o37TETh1wNhHiNPWSiwvxPvyPBQqtKi6rstmRqgXdg24+DVHAzDKqJfew4xc1qnVvjeeJrgsS0VBrLQvwlrte0LdXvPQmRDAEoqCUyyJLbNxuh/913ipBEvMWvvLDBR9sUiEmltY65EAIaeewzwLOYj1RPr9WKx/bxwGEBe/PbIA54TUnek107Fdg2LHPTFC4YWSkC2qr25Uw6ZPiITP3yOXj1lCFUCf7bV2Efp1mfSxuBhdkNWPQQqm3ErCjgnIoRHs40lUkJRQY/+329aYsHimD0M3ltEIazOaEfZl+bPhg0Z1oGseeSkq6pE7PH18OQlDnhFpHpEKndXZCjjR1twc+b5/CIcioaRWXl8eiRc2XsfHWk02Wp9FhRNmNDtvx5YkhpSs+kTkEriD1CE/EDestGRodlHC4g4mOKPb/uaEEm+SjMaLlgzZLHBlC1AR/sgqUMLhFex0u3RYF3nIY7XpHwsJdlRV1YPS/DMAZQY2N6X0DyRzVJHOgUlcRlcAcxIbqVbee1ls37QZ2nyJRdvQ7Ry5Smb+eyFanjNF/69WLtai2dNJPiUrNXRdHs0RPXqwVxnYQHp8Wvh4CteeT/ENnQvvkWrf/RpkLekNjTmkSbRSGpljzoDm0sGlBM+nQhe0qj5YX23l445gghZoTiXYwu3sw6tg2I84d1Hldt7uFR87nquWv06GiLCWX81Rhi7SZtjMIlBo+GDKXtrUxov0lYeDmDzh9o14knXNGANUO3PHg62n66OtrXQHuvif0wARDzx+81k0J4IaW13B86pJfOUq56YRejlrlAj097SY9X4ObQ+4JHTWsb5g6CCtY65RpV0lZuLFKVzh+Er2MQu8V2ZeLVuDG0dtINRavTTnIvKkU1+13mkxh2qqBf7Ou0t09oE/1GdKmQrer4zMQXm0d9idwzND9U/QCkXhWj+Y1zNYPvXnGCSGEavqnlMrjVWx7W5/QcluH3i6DWk9jjLKh3dyAO945AB1SBw8KjTsG01Gx/UCRVSnGjr7puCKbfQwo+0MQUm8zFIdEiBRbtk6er8JeuYlVWwxdH2BGRf7uqGNwsUddsZsHTzYgzEd5zv4qT3Lvx2uQAz88YSr48Teh3aCsPhXbw/mgsur9HfjYclV52bb3+glHQ52tNEsJBwkKSa73FMSperYSwwdq1y7jWmcBVcpAmQ2OdSnvgpGlCnT5obRhLpgGIEZnPUxwrrdDYmiAQCZxus0kpmF4Q7HjmVo3HaPYCu59rfgmPJQVffgJphIPP8NY6GzIsi23+qnt7RCtdJNbD3Zb6bu7ewiHekSU5tXuIcFDPXpLTpfYRlE9mWHVFtmK5o1x0NZNbaVOqwSHaZRBM+sOdSw3+UCqgUv5dLqwPTEYosdsEk1aNE6JaEwSSXe5uJG2f2vzC/UCcMzqeH5Wa8Ldc/aEq70l38zoTeC5DhOPHBIb81Q1Y/Z1/B5uKRpLU/anxijs/uGMiQLuaC7ObRKjlVLkVbXfw1d2PIRbVAxN6sAGX63HC1+3M3z35vW3z19ccGoZewVyv9VjHNn08B1bbTr1vk7c7EK5rdTaF59DSIFuN0kNYd0rfayZFGSlpnrBwfYlV5FuXnry6MmTL8+ejJ1GAX3Kok76Rh/3gQivt8Wxp7bL79uBhJraXd/RuekUM3vr3u7BnKoipi2Y31I0704+KJn/JrXnW3ILbVm5pQh9vKXU/ndarfrUerU9pi29eLxifUuKok/T3ikt4Uq3lSRNjnNz2Zd+6GiBoQTEHcvrv6jE/gvL7IaSAYb96tX2X7PiPiBht9XcW1G9avhqpwjMVStLoFl1uz1TPqXbaYjmTZfpO62MqkRvqveOmdOds79mvZ5TZO9FhbXQ+fD7X923Jtsc19Oom32i4WmO62s7i1rUM+7PXrZewcFeBax2UyNowBVzt8u9VTjXgBeqdxiOaXs7eKZuRQDY/W0Dfe+98FRMh+mUBTiq2kTqkrcd1M2Z3ebgYB2BkcOqlJMnYUcHW6FSFTd0QjTNO/tygpN8Y5idpJu6edPnMMGe6Rc4Cgh4pSnc9DgLemXsG1Q/b7qHaMrfjAjY3ZtrFa2OIlyhmlfual9Hd2dDWl7qmWojwtST9zXs+AX9RFUHNlMgcw8zOnTbZuXoMpxGtFoUYWw4M+2w/HDUNj3dd9D43PKkziKHNoJenc0dt7rlY1PDJ0bht7rZ/V4uzdU7Rhdhb7ZSwVbR+HLcfcCZAOQRD1HAusdChQQqdMdIgkqc6jZ4/TSr5wy0V1Nl1MPkWu+mnzuG7aSNd1e037v5BWJwBKW2zDsWdq7sq8ljzS2E3rgFA8SJAqc2VJW0R0c8ITfiQAgRz6HiCv646dbwe9wYk9HQ+JlXgdmh709q3D2ZYYZOt1fwG7uexfysfHx2Nub++AgsFDkKqlsa3a+hoo0pds/VuM8oWTCcH+/PlLgF6tNic3vTrQDRPevfnFSDPJ7/mBE9Dsj+tMusP+cyvqVa6aJqPnMWVQ3Hi/gqxV596Uw1OOA51yl0aiAB25nv9dE37zmYvLvvrKDaHAx49I3Jig98Ns3JXOsSgO7gUKD8m9uSLyyARWqLl+QREn6q5aAvIB4diwscATiWjunC6N/YU2RkAJIuTthAeLgaNeB6H80YkWzyizMRvpiWrdUntAahnRaun1A//yOlqUxa8W55qh7NdErKqpNq6jaYkH8bcTk4sk5uGKovipgU5GAkTJ8R2ZVOw0qovi1CWt3cpyt+pOjTJsE68ndt/tJfC+lakG7s1o98O/txdmg4lb99JI3eb4LDT4ynMJfOa3beQT90humNUjXU1ryWhzUvlTw3YNseHY5XJ+FwkPbuzJjwtBysm1bXtRJ2cZSUoyga/e2IOUcSt/G7P/L4BTxnMEMHvFc/WJ6ccN4ZlDZXK1FfC2E+v6Cjg9YXRqmBoP2JCfNGOpa6FcImrloefFjCBnF0wvXsBcd8y5Ao+Hg1M3AXVxwhX/FXGDhh67wievMpIaql2Zj7IRr7o8C2FSbjBMy6Yyh4V6WiPkXkKJU0iy+LElZMJvyi9VG9MuBZnR8qmD/Qxh7sKEvxoPhqrw/N/2HCzGi3udfZY7bbcMZ/FlXp/++I51FH2C9P0MNxfy9H2B9O9pLbaWC14WrrJYIhMKxoK+WeUmrBP5KAwLeAPRNY/b65iEFP5v/TEr9zWuLWnsfTmqIO9Xk7AlFvBRwo+c6J+HUyKYedl/MjfZf6CMY7if01HHvZCWyCTknPHAr5nZM0KjojNxWN2K+Yo8EG2sC8c1NJOr36Q9vTp+qtqu/oSZAKbj/Hd42jKC0TiBScmVOI4szr3oENB1Aw52ikxjrSSR3MBufqqOGTppvI4vQpbptFTJ+inIOiBQ0Q1TDVPzJX51Kwu6O6lHPDvzcXL58+f/XNxRvzaj69Pcsw6A9CkbbRWPcBwM2pulycz+hdvta92fkSG0wX2ES/JEPReu70LBJEfAFyYaGYbB/P7HVTHAOm8BXqHUgFk194lPz+Y01vy+C3FfCLFng0cYj6Fg37+vzpLWlbBfHTEZ2iECJ6fq4/koMvLHYGqBFDuNFKRBYtzJ6+eo9QC4Jpw3JykprleLO3vjPWz2n4cAmIXpHhMZ26D0cLQFkpsS9NNFkahLiHZ0PEmKyAzqV45U5UcY2v9iBzPwA70ckynwbRR0Z1pVPpR1eubJfKwn/29M3fXkfv4N+Ld9E3z9+As3iUIuf1Auqoe/M9iMnL56+it++ePvsP1UuoGjr8IWqMT/jEe5l97VE3iKfAUkmyHQX2LPv29fdvnl1Eb//+lJekHbHhWXc4CjPITd/wIRxdH5ZcVwXdRZPFvt3LN9i+56xpeviGTuFQttyBga/GwWxj3LHFPIpQhUeRYjx77G/3EHxtL8A2Bazgw9F/A8GIrtPIYgAA","sha256":"166dbc2047e0ce57e697da3e68326823aae0376221600fec18881f41f899250f"},"maintenance":{"blob":"436049145abae26d751988fbfd74a6d5e780b06c","bytes":12668,"gzip_base64":"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","sha256":"6003482e759a36b7d7ed82814071b894900b450653241679762898fddf9d98ca"}}')
REPO = Path(CONFIG['repo'])
CALLER = Path('/home/qian-qi/hepta-learn-caller-20261112-037c-726af8f4')
ROOT = Path('/home/qian-qi/hepta-learn-037c-evidence')
TARGET = Path('/data/hepta-learn-037c-20261112/target-cold-4ab-v1')
BASE = CONFIG['prior_maintenance']['source']
BASE_TREE = CONFIG['prior_maintenance']['tree']
BASE_INVENTORY = None  # Historical 14995 inventory never applies to this complete source.
LOCK = '98b3767c6e74bf6eeb5894db760259dbc400cbfd0685af8ad915c92d25408d69'
source, tree, request_key = CONFIG['source'], CONFIG['tree'], CONFIG['request_key']
RECORDS = ROOT / ('native-prepare-' + source[:12] + '-' + CONFIG['records_suffix'])
MAINTENANCE = (Path(CONFIG['prior_maintenance']['result']['path']).parent if CONFIG['maintenance_mode'] == 'consume-external-clean-terminal' else ROOT / ('maintenance-' + source[:12] + '-' + CONFIG['records_suffix']))
NATIVE = ROOT / ('native-' + source[:12] + '-' + CONFIG['records_suffix'])
if CONFIG.get('admission_frozen') is not True:
    raise SystemExit('NOT_SUBMITTED preview: actual passing source and natural terminal bindings are required')
RECORDS.mkdir(mode=0o700, exist_ok=False)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def meta(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(name, value):
    with (RECORDS / name).open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')


def git(*args, cwd=REPO):
    return subprocess.check_output(['git', '--no-optional-locks', *args], cwd=cwd)


def identity(cwd=REPO):
    sparse = Path(git('rev-parse', '--git-path', 'info/sparse-checkout', cwd=cwd).decode().strip())
    if not sparse.is_absolute():
        sparse = cwd / sparse
    return {'commit': git('rev-parse', 'HEAD', cwd=cwd).decode().strip(),
            'tree': git('rev-parse', 'HEAD^{tree}', cwd=cwd).decode().strip(),
            'status': git('status', '--porcelain=v1', '--untracked-files=all', cwd=cwd).decode(),
            'diff_sha256': hashlib.sha256(git('diff', '--binary', 'HEAD', '--', cwd=cwd)).hexdigest(),
            'cargo_lock_sha256': sha(cwd / 'codex-rs/Cargo.lock'),
            'sparse_path': str(sparse.resolve()), 'sparse_sha256': sha(sparse) if sparse.is_file() else None}


def inventory():
    rows = []
    names = git('ls-files', '-z') + git('ls-files', '--others', '--exclude-standard', '-z')
    for raw in sorted(set(names.split(b'\0')) - {b''}):
        rel = os.fsdecode(raw)
        path = REPO / rel
        if not path.exists() and not path.is_symlink():
            rows.append({'path': rel, 'missing': True})
            continue
        data = os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
        mode = '120000' if path.is_symlink() else ('100755' if path.stat().st_mode & 0o111 else '100644')
        rows.append({'path': rel, 'mode': mode, **meta(data)})
    encoded = json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()
    return rows, encoded


def snapshot(label):
    rows, encoded = inventory()
    with gzip.open(RECORDS / (label + '.files.json.gz'), 'xb') as stream:
        stream.write(encoded)
    observed = {**identity(), 'files': len(rows), 'inventory_sha256': hashlib.sha256(encoded).hexdigest()}
    save(label + '.json', observed)
    return observed, rows, encoded


def retain_changes(label):
    patch = git('diff', '--binary', 'HEAD', '--')
    (RECORDS / (label + '.patch')).write_bytes(patch)
    names = git('diff', '--name-only', '--no-renames', '-z', 'HEAD', '--')
    names += git('ls-files', '--others', '--exclude-standard', '-z')
    rows = []
    for raw in sorted(set(names.split(b'\0')) - {b''}):
        rel = os.fsdecode(raw)
        path = REPO / rel
        if not path.exists() or path.is_symlink():
            rows.append({'path': rel, 'missing': not path.exists(), 'symlink': path.is_symlink()})
            continue
        data = path.read_bytes()
        destination = RECORDS / (label + '-postimages') / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as stream:
            stream.write(data)
        rows.append({'path': rel, **meta(data)})
    value = {'patch': meta(patch), 'files': rows}
    save(label + '-postimages.json', value)
    return value


def execute(label, command, cwd, env):
    started = now()
    path = RECORDS / (label + '.raw.log')
    digest, size = hashlib.sha256(), 0
    with path.open('xb', buffering=0) as stream:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        save(label + '-launch.json', {'command': command, 'cwd': str(cwd), 'pid': process.pid,
             'started_at': started, 'controller_timeout_or_kill': False})
        print(json.dumps({'phase': label, 'pid': process.pid, 'started_at': started}), flush=True)
        while True:
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                break
            stream.write(chunk)
            digest.update(chunk)
            size += len(chunk)
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
        returncode = process.wait()
        process.stdout.close()
        os.fsync(stream.fileno())
    observed = {'command': command, 'cwd': str(cwd), 'started_at': started, 'finished_at': now(),
                'returncode': returncode, 'actual_process_exit_observed': True, 'controller_kill': False,
                'log_file': path.name, 'log_bytes': size, 'log_sha256': digest.hexdigest()}
    save(label + '.json', observed)
    return observed


def pinned_original(spec, label):
    path = Path(spec['path'])
    assert path.is_absolute() and path.is_relative_to(ROOT), label
    data = path.read_bytes()
    assert len(data) == spec['bytes'] and hashlib.sha256(data).hexdigest() == spec['sha256'], label
    with (RECORDS / (label + '.original.json')).open('xb') as stream:
        stream.write(data)
    return path, json.loads(data)


def source_gate_admission():
    path, gate = pinned_original(CONFIG['source_gate']['result'], 'source-gate-result')
    execution_path, execution = pinned_original(CONFIG['source_gate']['execution'], 'source-gate-execution')
    assert gate['source'] == source and gate['tree'] == tree
    assert gate['status'] == 'passed' and gate['exit_code'] == 0
    assert gate['before'] == gate['after'] and gate['after']['dirty'] == ''
    assert gate['after']['commit'] == source and gate['after']['tree'] == tree
    assert gate['execution']['returncode'] == 0 and gate['execution']['actual_process_exit_observed']
    assert gate['execution']['outer_controller_kill'] is False
    assert execution['source_sha'] == execution['tested_sha'] == source
    assert execution['status'] == 'passed' and execution['exit_code'] == execution['command_exit_code'] == execution['returncode'] == 0
    assert execution['before'] == execution['after'] and execution['after']['dirty'] is False
    assert execution['after']['commit'] == source and execution['after']['tree'] == tree
    assert execution['timed_out'] is False and execution['output_limit_exceeded'] is False
    assert execution['minimum_tests'] == 1 and execution['observed_failed_tests'] == 0
    assert execution['observed_passed_tests'] == CONFIG['source_gate']['expected_cases']
    assert execution['command'] == ['python3', '-m', 'unittest', 'discover', '-s', 'qa/b4-no-bypass', '-p', '*source_closure.py', '-v']
    assert execution['lane'] == 'source-head'
    assert Path(execution['working_directory']) == Path(CONFIG['source_gate']['repo'])
    log = execution_path.parent / execution['log_file']
    assert log.is_relative_to(execution_path.parent)
    assert log.stat().st_size == execution['log_bytes'] and sha(log) == execution['log_sha256']
    compressed = path.parent / 'source-after.files.json.gz'
    data = gzip.decompress(compressed.read_bytes())
    assert hashlib.sha256(data).hexdigest() == gate['after']['inventory_sha256']
    rows = json.loads(data)
    assert len(rows) == gate['after']['file_count'] and not any(row.get('missing') for row in rows)
    assert rows == sorted(rows, key=lambda row: os.fsencode(row['path']))
    assert len({row['path'] for row in rows}) == len(rows)
    assert data == json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()
    assert all(set(row) == {'path', 'mode', 'bytes', 'sha256'} for row in rows)
    save('source-gate-admission.json', {'result': CONFIG['source_gate']['result'],
         'execution': CONFIG['source_gate']['execution'], 'observed': gate['after'],
         'source_closure_cases': execution['observed_passed_tests'],
         'source_closure_log_sha256': execution['log_sha256'],
         'source_inventory_schema': 'path/mode/bytes/sha256; no Git blob',
         'native_inventory_schema': 'path/mode/bytes/sha256/blob; compared explicitly below'})
    return gate, data


def prior_maintenance_admission():
    path, previous = pinned_original(CONFIG['prior_maintenance']['result'], 'prior-maintenance-result')
    assert previous['source_sha'] == CONFIG['prior_maintenance']['source']
    assert previous['source_tree'] == CONFIG['prior_maintenance']['tree']
    # This earlier natural terminal releases the shared target. It grants no
    # native admission: the new source still executes its own clean fmt/fix below.
    expected_exit = CONFIG['prior_maintenance']['expected_exit_code']
    assert expected_exit in (0, 101)
    assert previous['status'] == ('passed' if expected_exit == 0 else 'failed')
    assert previous['exit_code'] == previous['execution']['returncode'] == expected_exit
    assert previous['execution']['actual_process_exit_observed'] and previous['execution']['controller_kill'] is False
    assert previous['before'] == previous['after'] and previous['after']['dirty'] == ''
    assert previous['postimages']['file_count'] == previous['postimages']['patch_bytes'] == 0
    assert json.loads((path.parent / 'postimages.json').read_text())['files'] == []
    assert (path.parent / 'maintenance.patch').read_bytes() == b''
    log = path.parent / previous['execution']['log_file']
    assert log.is_relative_to(path.parent)
    assert log.stat().st_size == previous['execution']['log_bytes'] and sha(log) == previous['execution']['log_sha256']
    data = gzip.decompress((path.parent / 'source-after.files.json.gz').read_bytes())
    assert hashlib.sha256(data).hexdigest() == previous['after']['inventory_sha256']
    assert len(json.loads(data)) == previous['after']['file_count']
    return previous, data


def verify_full_index_and_bytes(rows, commit, label='source'):
    assert not any(row.get('missing') for row in rows)
    index = {}
    for raw in git('ls-files', '--stage', '-z').split(b'\0'):
        if not raw:
            continue
        fields, name = raw.split(b'\t', 1)
        mode, blob, stage = fields.decode().split()
        assert stage == '0' and os.fsdecode(name) not in index
        index[os.fsdecode(name)] = (mode, blob)
    objects = {}
    for raw in git('ls-tree', '-r', '-z', '--full-tree', commit).split(b'\0'):
        if not raw:
            continue
        fields, name = raw.split(b'\t', 1)
        mode, kind, blob = fields.decode().split()
        assert kind == 'blob' and os.fsdecode(name) not in objects
        objects[os.fsdecode(name)] = (mode, blob)
    actual = {row['path']: (row['mode'], row['blob']) for row in rows}
    assert len(actual) == len(rows) and actual == index == objects, 'full source/index/tree disagreement'
    save(label + '-full-tree-index-admission.json', {'commit': commit, 'file_count': len(rows),
         'every_actual_mode_and_blob_equals_full_index_and_tree': True,
         'missing_files': 0, 'untracked_inputs': 0, 'sparse_inputs_accepted': False})


def admit_exact_checkout(before, rows, encoded, previous, previous_bytes, gate, gate_bytes, origin):
    mode = CONFIG['source_admission_mode']
    assert mode in ('prepared-newcheckout', 'reuse-qa-only-fast-forward')
    if mode == 'prepared-newcheckout':
        assert before['commit'] == source and before['tree'] == tree and before['status'] == ''
        assert git('rev-parse', source + '^{tree}').decode().strip() == tree
        assert git('rev-list', '--parents', '-n', '1', source).decode().strip().split() == [source, CONFIG['parent']]
        save('checkout-admission.json', {'mode': mode, 'source_writes': False,
             'fetch': False, 'checkout': False, 'new_full_worktree': str(REPO)})
    else:
        # This branch is only the reviewed four-QA direct child, never a product fix.
        base = CONFIG['qa_fast_forward']['base']
        base_tree = CONFIG['qa_fast_forward']['base_tree']
        files = CONFIG['qa_fast_forward']['files']
        assert len(files) == 4 and len({row['path'] for row in files}) == 4
        assert all(row['path'].startswith('qa/b4-no-bypass/') and row['path'].endswith('_source_closure.py') for row in files)
        assert before['commit'] == base and before['tree'] == base_tree and before['status'] == ''
        assert CONFIG['parent'] == base and previous['source_sha'] == base and previous['source_tree'] == base_tree
        assert previous['exit_code'] == 0, 'QA-only fast-forward requires an actually successful prior compiler'
        assert before['inventory_sha256'] == previous['after']['inventory_sha256'] and encoded == previous_bytes
        verify_full_index_and_bytes(rows, base, label='prior-source')
        by_path = {row['path']: row for row in rows}
        for item in files:
            assert by_path[item['path']] == {'path': item['path'], 'mode': '100644', **item['base']}, item['path']
        fetched = execute('fetch-exact-qa-child', ['git', 'fetch', 'origin', source], REPO, os.environ.copy())
        assert fetched['returncode'] == 0
        assert git('rev-parse', source + '^{tree}').decode().strip() == tree
        assert git('rev-list', '--parents', '-n', '1', source).decode().strip().split() == [source, base]
        changed = git('diff', '--name-status', '--no-renames', '-z', base, source).split(b'\0')
        assert changed[-1] == b'' and len(changed[:-1]) == 8
        pairs = list(zip(changed[:-1:2], changed[1:-1:2]))
        assert sorted((status.decode(), os.fsdecode(path)) for status, path in pairs) == sorted(('M', item['path']) for item in files)
        assert git('rev-parse', base + ':codex-rs') == git('rev-parse', source + ':codex-rs')
        assert git('rev-parse', base + ':CALLERS.toml') == git('rev-parse', source + ':CALLERS.toml')
        for item in files:
            assert meta(git('show', source + ':' + item['path'])) == item['after'], item['path']
            by_path[item['path']] = {'path': item['path'], 'mode': '100644', **item['after']}
        expected = json.dumps([by_path[row['path']] for row in rows], sort_keys=True, separators=(',', ':')).encode()
        save('qa-fast-forward-admission.json', {'base': before, 'child': source, 'tree': tree,
             'files': files, 'full_expected_native_inventory_sha256': hashlib.sha256(expected).hexdigest(),
             'codex_rs_tree_unchanged': True, 'CALLERS_unchanged': True,
             'reset_clean_restore_used': False, 'prior_actual_clean_maintenance': CONFIG['prior_maintenance']['result']})
        checked = execute('checkout-exact-qa-child', ['git', 'checkout', '--detach', source], REPO, os.environ.copy())
        assert checked['returncode'] == 0
    observed, current_rows, current_bytes = snapshot('exact-source')
    assert observed['commit'] == source and observed['tree'] == tree and observed['status'] == ''
    assert observed['cargo_lock_sha256'] == LOCK
    assert observed['sparse_path'] == before['sparse_path'] and observed['sparse_sha256'] == before['sparse_sha256']
    assert git('remote', 'get-url', '--all', 'origin').decode().splitlines() == origin
    if mode == 'reuse-qa-only-fast-forward':
        assert current_bytes == expected, 'checked-out QA child differs from the exact four reviewed postimages'
    without_blob = [{key: value for key, value in row.items() if key != 'blob'} for row in current_rows]
    actual_gate_bytes = json.dumps(without_blob, sort_keys=True, separators=(',', ':')).encode()
    assert actual_gate_bytes == gate_bytes
    assert len(current_rows) == gate['after']['file_count']
    assert hashlib.sha256(actual_gate_bytes).hexdigest() == gate['after']['inventory_sha256']
    verify_full_index_and_bytes(current_rows, source)
    return observed, current_rows, current_bytes


result = {'source': source, 'tree': tree, 'base': BASE, 'request_key': request_key,
          'diagnostic_only': True, 'ordinary_qualification': 0, 'root_qualification': 0,
          'formal_focused_qualification': False, 'started_at': now(), 'status': 'preflight'}
save('intent.json', {'config': CONFIG, 'drivers': {name: {k: v for k, v in item.items() if k != 'gzip_base64'}
     for name, item in BUNDLED_DRIVERS.items()}, 'uid': os.getuid(), 'gid': os.getgid(),
     'rendered_wrapper_sha256_from_frozen_launcher': sys.argv[1] if len(sys.argv) == 2 else None})
caller_before = None
source_ready = None
source_bytes = None
exit_code = 1
try:
    assert os.getuid() != 0
    assert len(source) == len(tree) == 40 and all(ch in '0123456789abcdef' for ch in source + tree)
    assert len(CONFIG['required_names']) == len(set(CONFIG['required_names'])) == 11
    assert not NATIVE.exists()
    assert CONFIG['maintenance_mode'] in ('in-pipeline', 'consume-external-clean-terminal')
    assert (MAINTENANCE.is_dir() if CONFIG['maintenance_mode'] == 'consume-external-clean-terminal' else not MAINTENANCE.exists())
    gate, gate_bytes = source_gate_admission()
    previous, previous_bytes = prior_maintenance_admission()
    before, before_rows, before_bytes = snapshot('prior-source')
    assert before['status'] == '' and not any(row.get('missing') for row in before_rows)
    assert before['cargo_lock_sha256'] == LOCK and before['diff_sha256'] == hashlib.sha256(b'').hexdigest()
    caller_before = identity(CALLER)
    assert caller_before['status'] == '' and caller_before['commit'] == '726af8f4a345a2ffb148b971f3fa16c71436862d'
    assert before['sparse_path'] != caller_before['sparse_path']
    save('caller-before.json', caller_before)
    environment_path = ROOT / 'maintenance-4ab34bbd3ca8-v3/native-environment.json'
    assert sha(environment_path) == '682e2ad2b1dceeb0b643b8c10df1101bb5e27f1e1608d633d190134dbfc390cf'
    original_environment = json.loads(environment_path.read_text())
    env = dict(os.environ)
    for key, value in original_environment['environment'].items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    env.update(SOURCE_SHA=source, TESTED_SHA=source, HEPTA_CI_LANE='source-head',
               CODEX_REPO_ROOT=str(REPO), PYTHONPATH=str(REPO / 'scripts'))
    assert env['RUSTUP_TOOLCHAIN'] == '1.96.0' and env['CARGO_BUILD_JOBS'] == '2'
    assert env['CARGO_PROFILE_DEV_DEBUG'] == env['CARGO_PROFILE_TEST_DEBUG'] == '0'
    assert env['CARGO_NET_OFFLINE'] == 'true' and env['CARGO_TARGET_DIR'] == str(TARGET)
    inputs = []
    for expected in original_environment['native_inputs']:
        path = Path(expected['path'])
        assert path.stat().st_size == expected['bytes'] and sha(path) == expected['sha256'], str(path)
        inputs.append(expected)
    helper_path = ROOT / 'native-cc22a69972d0-focused-v1/helpers/manifest.json'
    assert sha(helper_path) == 'ca437cea08311d1ba5fdc237ff3e9c89261b78783c8a0f6eb06c98d02673072c'
    helper = json.loads(helper_path.read_text())
    assert helper['complete'] and helper['exit_code'] == 0
    retained_helpers = []
    for name, expected in helper['artifacts'].items():
        path = Path(expected['executable'])
        assert path.stat().st_size == expected['bytes'] and sha(path) == expected['sha256'], name
        retained_helpers.append({'name': name, 'path': str(path), 'bytes': expected['bytes'], 'sha256': expected['sha256']})
    # Observe before deciding: the prior conjunction does not prove why admission failed.
    try:
        prior_target = TARGET.lstat()
    except FileNotFoundError:
        prior_target = None
    target_before = {'path': str(TARGET), 'exists': prior_target is not None}
    if prior_target is not None:
        target_before.update(device=prior_target.st_dev, inode=prior_target.st_ino,
                             uid=prior_target.st_uid, mode=prior_target.st_mode,
                             symlink=stat.S_ISLNK(prior_target.st_mode),
                             directory=stat.S_ISDIR(prior_target.st_mode))
    save('target-before.json', target_before)
    for ancestor in reversed(TARGET.parents):
        observed_parent = ancestor.lstat()
        assert stat.S_ISDIR(observed_parent.st_mode) and not stat.S_ISLNK(observed_parent.st_mode), str(ancestor)
    parent_stat = TARGET.parent.lstat()
    assert parent_stat.st_uid == os.getuid(), 'target parent is not the original operator-owned task parent'
    if prior_target is not None:
        assert stat.S_ISDIR(prior_target.st_mode) and not stat.S_ISLNK(prior_target.st_mode)
        assert prior_target.st_uid == os.getuid(), 'existing target owner differs; do not adopt or overwrite'
    concurrent = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdecimal():
            continue
        try:
            comm = (proc / 'comm').read_text().strip()
            if comm not in {'cargo', 'rustc', 'rustdoc', 'rustfmt', 'cargo-clippy', 'clippy-driver', 'just', 'cargo-nextest', 'sccache'} and not comm.startswith('codex_hepta'):
                continue
            row = {'pid': int(proc.name), 'comm': comm, 'uid': proc.stat().st_uid}
            for name in ('exe', 'cwd'):
                try:
                    row[name] = os.readlink(proc / name)
                except OSError as error:
                    row[name + '_error'] = type(error).__name__
            concurrent.append(row)
        except (FileNotFoundError, PermissionError):
            continue
    own_roots = (str(REPO), str(TARGET), '/home/qian-qi/hepta-learn-common-20261112-037c')
    own_source_prefix = '/home/qian-qi/hepta-learn-source-20261112-037c-'
    assert not any(any(row.get('cwd', '') == root or row.get('cwd', '').startswith(root + '/') for root in own_roots)
                   or row.get('cwd', '').startswith(own_source_prefix)
                   or row.get('exe', '').startswith(str(TARGET) + '/') for row in concurrent), 'active tooling in own source or target'
    target_created = False
    if prior_target is None:
        # Exactly one missing task-owned directory; never clean, replace, chmod or chown an existing target.
        current_parent = TARGET.parent.lstat()
        assert current_parent.st_dev == parent_stat.st_dev and current_parent.st_ino == parent_stat.st_ino
        assert current_parent.st_uid == os.getuid() and stat.S_ISDIR(current_parent.st_mode)
        TARGET.mkdir(mode=0o700, exist_ok=False)
        target_created = True
    target_stat = TARGET.lstat()
    assert stat.S_ISDIR(target_stat.st_mode) and not stat.S_ISLNK(target_stat.st_mode)
    assert target_stat.st_uid == os.getuid()
    if prior_target is not None:
        assert target_stat.st_dev == prior_target.st_dev and target_stat.st_ino == prior_target.st_ino
    target_nonempty = any(TARGET.iterdir())
    if target_created:
        assert not target_nonempty, 'new cold target must actually be empty'
    save('target-admission.json', {'before': target_before, 'created': target_created,
         'empty_on_admission': not target_nonempty, 'device': target_stat.st_dev,
         'inode': target_stat.st_ino, 'uid': target_stat.st_uid,
         'existing_data_removed': False, 'existing_metadata_modified': False})
    save('environment-admission.json', {'previous_environment_sha256': sha(environment_path),
         'environment': {key: env.get(key) for key in original_environment['environment']},
         'native_inputs': inputs, 'retained_helpers': retained_helpers,
         'target': {'path': str(TARGET), 'device': target_stat.st_dev, 'inode': target_stat.st_ino,
                    'uid': target_stat.st_uid, 'reused_existing_cache': not target_created and target_nonempty,
                     'created': target_created, 'empty_on_admission': not target_nonempty},
         'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
         'concurrent_rust_processes': concurrent, 'other_processes_touched': False,
         'available_disk_bytes': os.statvfs(TARGET).f_bavail * os.statvfs(TARGET).f_frsize,
         'memory': [line for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemTotal:', 'MemAvailable:'))]})
    rustfmt = subprocess.check_output(['/home/qian-qi/.cargo/bin/rustup', 'which', '--toolchain', '1.96.0', 'rustfmt'], env=env).decode().strip()
    assert sha(Path(rustfmt)) == '342c3d56e8958da0b108108a39e37ceac64ebdd42e6eefafa237d219e5b7eb0c'
    tools = {}
    for name in ('rustc', 'cargo', 'rustfmt'):
        path = Path(subprocess.check_output(['/home/qian-qi/.cargo/bin/rustup', 'which', '--toolchain', '1.96.0', name], env=env).decode().strip())
        tools[name] = {'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha(path)}
    just = Path(shutil.which('just', path=env['PATH']))
    tools['just'] = {'path': str(just), 'bytes': just.stat().st_size, 'sha256': sha(just)}
    save('tool-inputs.json', tools)
    origin = git('remote', 'get-url', '--all', 'origin').decode().splitlines()
    assert len(origin) == 1
    origin_bytes = origin[0].encode()
    if origin[0].startswith('git@github.com:'):
        repository = origin[0].split(':', 1)[1]
    else:
        parsed = urllib.parse.urlsplit(origin[0])
        assert parsed.hostname == 'github.com' and parsed.scheme in ('https', 'ssh')
        repository = parsed.path.lstrip('/')
    assert repository.removesuffix('.git') == 'TrillionniumFoundation/hepta-private-ci'
    save('origin-admission.json', {'repository': 'TrillionniumFoundation/hepta-private-ci', 'origin_sha256': hashlib.sha256(origin_bytes).hexdigest(), 'configuration_changed': False})
    source_ready, new_rows, source_bytes = admit_exact_checkout(
        before, before_rows, before_bytes, previous, previous_bytes, gate, gate_bytes, origin)
    assert identity(CALLER) == caller_before
    for rel in ('docs/modules/MODULES.json', 'qualification/neuron-v13-generation/proposal_worker.py'):
        assert (REPO / rel).read_bytes() == git('show', source + ':' + rel), rel
    assert sha(REPO / 'AGENTS.md') == 'c3f80e8386eb170b00af1e21de40d770c4941e464915687e728e2d14a7e79480'
    assert not (REPO / 'codex-rs/AGENTS.md').exists() and not list((REPO / 'codex-rs/hepta-agentd').rglob('AGENTS.md'))
    workflow = (REPO / '.github/workflows/hepta-daemon-learning-native.yml').read_bytes()
    assert meta(workflow)['blob'] == CONFIG['workflow_blob']
    marker = '          cat > "$RUNNER_TEMP/daemon-learning-driver.py" <<\'PY\'\n'
    original = textwrap.dedent(workflow.decode().split(marker, 1)[1].split('          PY\n', 1)[0])
    declarations = {node.targets[0].id: ast.literal_eval(node.value) for node in ast.parse(original).body
                    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in ('parents', 'packages')}
    assert len(declarations['parents']) == len(set(declarations['parents'])) == CONFIG['root_parent_count'] == 33
    nextest = (REPO / 'codex-rs/.config/nextest.toml').read_bytes()
    assert meta(nextest)['blob'] == '0904c42a41594d3ae4dc6f196e64f35f0b85bd2c'
    assert 'slow-timeout = { period = "30s", terminate-after = 2 }' in nextest.decode()
    result.update(status='source-ready', source_ready=source_ready)
    save('source-ready.json', result)
    print(json.dumps({'phase': 'exact-source-ready', 'identity': source_ready}), flush=True)
    if CONFIG['maintenance_mode'] == 'in-pipeline':
        fmt = execute('just-fmt', ['just', 'fmt'], REPO / 'codex-rs', env)
        fmt_after, _, fmt_bytes = snapshot('fmt-source-after')
        fmt_images = retain_changes('fmt')
        assert fmt['returncode'] == 0 and fmt_bytes == source_bytes and fmt_after == source_ready and not fmt_images['files'] and fmt_images['patch']['bytes'] == 0, 'format failed or changed source; retained originals'
    else:
        # Consume the original natural fmt/fix terminal; do not run either again.
        assert CONFIG['source_admission_mode'] == 'prepared-newcheckout'
        assert previous['source_sha'] == source and previous['source_tree'] == tree and previous['exit_code'] == 0
        assert previous['before'] == previous['after_format'] == previous['after']
        assert previous_bytes == source_bytes
        fmt = previous['format_execution']
        assert fmt['command'] == ['just', 'fmt'] and fmt['returncode'] == 0
        assert fmt['actual_process_exit_observed'] and fmt['controller_kill'] is False
        fmt_log = MAINTENANCE / fmt['log_file']
        assert fmt_log.is_relative_to(MAINTENANCE)
        assert fmt_log.stat().st_size == fmt['log_bytes'] and sha(fmt_log) == fmt['log_sha256']
        save('external-format-terminal.json', {'original': fmt, 'source_bytes_equal': True,
             'original_result': CONFIG['prior_maintenance']['result'], 'format_rerun': False})
    driver_paths = {}
    for name, item in BUNDLED_DRIVERS.items():
        data = gzip.decompress(base64.b64decode(item['gzip_base64'], validate=True))
        assert meta(data) == {key: item[key] for key in ('bytes', 'sha256', 'blob')}
        path = RECORDS / (name + '.py')
        with path.open('xb') as stream:
            stream.write(data)
        driver_paths[name] = path
    if CONFIG['maintenance_mode'] == 'in-pipeline':
        maintenance_command = ['/usr/bin/python3', str(driver_paths['maintenance']), '--mode', 'fix', '--source', source, '--tree', tree, '--records', str(MAINTENANCE), '--request-key', request_key]
        fixed = execute('maintenance-process', maintenance_command, REPO, env)
        maintained = json.loads((MAINTENANCE / 'result.json').read_text())
        save('maintenance-terminal.json', {'process': fixed, 'result_sha256': sha(MAINTENANCE / 'result.json'), 'result': maintained})
    else:
        maintained = previous
        fixed = maintained['execution']
        assert fixed['command'] == ['just', 'fix', '-p', 'codex-hepta-agentd', '--locked', '--offline']
        assert sha(MAINTENANCE / 'result.json') == CONFIG['prior_maintenance']['result']['sha256']
        save('maintenance-terminal.json', {'original_execution': fixed,
             'result_sha256': sha(MAINTENANCE / 'result.json'), 'result': maintained,
             'maintenance_rerun': False, 'source_bytes_equal': True})
    assert fixed['returncode'] == 0 and maintained['status'] == 'passed' and maintained['exit_code'] == 0
    assert maintained['source_sha'] == source and maintained['source_tree'] == tree
    assert maintained['execution']['returncode'] == 0 and maintained['execution']['actual_process_exit_observed'] and not maintained['execution']['controller_kill']
    assert maintained['before'] == maintained['after'] and maintained['after']['dirty'] == ''
    assert maintained['after']['inventory_sha256'] == source_ready['inventory_sha256'] and maintained['after']['cargo_lock_sha256'] == LOCK
    assert maintained['postimages']['file_count'] == 0 and maintained['postimages']['patch_bytes'] == 0
    assert json.loads((MAINTENANCE / 'postimages.json').read_text())['files'] == [] and (MAINTENANCE / 'maintenance.patch').read_bytes() == b''
    assert sha(MAINTENANCE / 'just-fix.raw.log') == maintained['execution']['log_sha256']
    assert gzip.decompress((MAINTENANCE / 'source-after.files.json.gz').read_bytes()) == source_bytes
    maintained_environment = json.loads((MAINTENANCE / 'native-environment.json').read_text())
    assert maintained_environment['environment'] == {key: env.get(key) for key in maintained_environment['environment']}
    assert maintained_environment['native_inputs'] == inputs
    native_preflight, _, native_preflight_bytes = snapshot('native-preflight')
    assert native_preflight == source_ready and native_preflight_bytes == source_bytes
    assert TARGET.stat().st_ino == target_stat.st_ino and TARGET.stat().st_dev == target_stat.st_dev
    for expected in inputs:
        assert sha(Path(expected['path'])) == expected['sha256']
    native_env = env.copy()
    native_env['RUST_MIN_STACK'] = '8388608'
    command = ['/usr/bin/python3', str(driver_paths['diagnostic']), '--repo', str(REPO), '--records', str(NATIVE), '--source', source, '--suite', 'diagnostic-eleven']
    save('native-admission.json', {'source': source_ready, 'maintenance_result_sha256': sha(MAINTENANCE / 'result.json'),
         'command': command, 'stack_bytes': 8388608, 'test_threads': 2, 'retries': 0,
         'nextest_per_case_seconds': 60, 'helper_outer_seconds': 3600, 'test_outer_seconds': 7200,
         'required_names': CONFIG['required_names'], 'diagnostic_only': True, 'ordinary_and_root': 'NOT_RUN'})
    tested = execute('native-process', command, REPO, native_env)
    driver_result_path = NATIVE / 'driver-result.json'
    if driver_result_path.is_file():
        driver_result = json.loads(driver_result_path.read_text())
        save('native-terminal.json', {'driver_result_sha256': sha(driver_result_path), 'driver_result': driver_result})
        expected_native_identity = {key: source_ready[key] for key in ('commit', 'tree', 'status', 'files', 'inventory_sha256')}
        assert driver_result['source_sha'] == source
        assert driver_result['source_before'] == driver_result['source_after'] == expected_native_identity
        if tested['returncode'] == 0:
            assert driver_result['status'] == 'passed' and driver_result['failures'] == []
    list_result_path = NATIVE / 'list-admission/result.json'
    list_coverage_path = NATIVE / 'list-admission/selected-name-coverage.json'
    list_admission = {'available': list_result_path.is_file() and list_coverage_path.is_file(), 'exact': False}
    if list_admission['available']:
        list_result = json.loads(list_result_path.read_text())
        list_coverage = json.loads(list_coverage_path.read_text())
        list_admission.update(result_sha256=sha(list_result_path), coverage_sha256=sha(list_coverage_path),
                              result=list_result, coverage=list_coverage)
        listed = [row['name'] for row in list_coverage['cases']]
        list_admission['exact'] = (len(listed) == len(set(listed)) == 11
                                   and sorted(listed) == sorted(CONFIG['required_names'])
                                   and list_coverage['exact_selected_names'] is True
                                   and list_result.get('native_test_child_started') is True
                                   and list_result.get('exit_code') == 0
                                   and list_result.get('status') == 'original-test-returned-zero'
                                   and list_result.get('budget_seconds') == 7200
                                   and list_result.get('budget_expired') is False
                                   and list_result.get('parent_signal_or_kill') is False
                                   and list_result['finished_monotonic'] < list_result['absolute_end_monotonic']
                                   and list_result['test_execution']['command'][:3] == ['just', 'test', '--locked']
                                   and list_result['list_execution']['returncode'] == 0
                                   and list_result['test_execution']['returncode'] == 0
                                   and list_result['source_before'] == list_result['source_after'])
    save('eleven-list-admission.json', list_admission)
    report = NATIVE / 'diagnostic-eleven.xml'
    checks = []
    coverage = {'available': report.is_file(), 'exact_pass_coverage': False, 'diagnostic_only': True}
    if report.is_file():
        nodes = list(ET.parse(report).getroot().iter('testcase'))
        for name in CONFIG['required_names']:
            matched = [node for node in nodes if node.attrib.get('name') == name]
            passed = len(matched) == 1 and not any(child.tag in ('error', 'failure', 'skipped', 'flakyFailure', 'flakyError', 'rerunFailure', 'rerunError') for node in matched for child in node)
            checks.append({'name': name, 'observed_count': len(matched), 'passed': passed, 'attributes': [dict(node.attrib) for node in matched]})
        coverage.update(junit=str(report), junit_sha256=sha(report), expected_count=11, observed_count=len(nodes), checks=checks,
                        exact_pass_coverage=len(nodes) == 11 and all(check['passed'] for check in checks))
    save('eleven-named-case-coverage.json', coverage)
    exit_code = 0 if tested['returncode'] == 0 and driver_result_path.is_file() and list_admission['exact'] and coverage['exact_pass_coverage'] else 1
    result.update(status='diagnostic-passed' if exit_code == 0 else 'diagnostic-failed', native_process=tested, named_case_coverage=coverage)
except BaseException as error:
    exit_code = 1
    result.update(status='failed', error=repr(error),
                  native_result_file_observed=(NATIVE / 'driver-result.json').is_file(),
                  native_launch_record_observed=(RECORDS / 'native-process-launch.json').is_file())
    traceback.print_exc()
finally:
    try:
        final, _, final_bytes = snapshot('source-after')
        result['source_after'] = final
        result['postimages'] = retain_changes('final')
        if source_ready is not None and (final != source_ready or final_bytes != source_bytes):
            result.update(status='failed', source_changed=True)
            exit_code = 1
        if caller_before is not None:
            caller_after = identity(CALLER)
            save('caller-after.json', caller_after)
            if caller_after != caller_before:
                result.update(status='failed', caller_changed=True)
                exit_code = 1
    except BaseException as error:
        result.update(status='failed', retention_error=repr(error))
        exit_code = 1
    result.update(finished_at=now(), exit_code=exit_code)
    save('result.json', result)
    print(json.dumps({'diagnostic_pipeline_result': result}, sort_keys=True), flush=True)
raise SystemExit(exit_code)
