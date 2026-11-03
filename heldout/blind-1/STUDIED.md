# blind-1 was studied: it is now a regression set

The first run (`reports/heldout/blind-1/first_run.json`, kept as recorded) passed 54 of 57 cases: all 29 checks and
25 of 28 close cases. Its failures were then read and the close agent changed, so this set no longer measures
anything blind. It stays in CI as a regression set (`--no-worse` against the first run), and `heldout/blind-2` was
written afterwards by a different author who had not seen the code or this set.

| Case | First run | Cause | Change |
|---|---|---|---|
| close-10 | deferrals for "Jahreslizenz 2027" and "Q1/2027" | the rules found no period, the model was asked and supplied the dates of a year and a quarter | a model period is used only when both ends are written in the notes, or the start and a stated length (`stated_in`) |
| close-21 | accruals for two suppliers whose latest invoice said the relationship ends ("endet unsere Zusammenarbeit", "Kündigung zum … bestätigen wir") | the end was detected by a fixed word list | contract ends are read per clause with patterns in `config/agents.yaml` (`close.contract_end`) |
| close-22 | no accrual for a supplier whose notes say the contract renews "sofern er nicht fristgerecht gekündigt wird" | "gekündigt" matched as a word | a clause that is a condition or a notice period does not end the contract |

`docs/AGENT_BEHAVIOUR.md` gained two sentences that the set's author had listed as ambiguities (1 and 9 in
`README.md`): what is not a stated period, and that notice periods and renewals are not ends. After the change the
set passes 57 of 57 (`latest_run.json`); the test month's release decision and numbers did not change.
