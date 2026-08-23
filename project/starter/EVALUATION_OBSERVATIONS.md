# Evaluation Observations

## Evaluation setup

The final automated test suite contains seven independent prompts covering:

- incomplete, ambiguous, and complete bug reports;
- an FAQ-covered account question;
- an FAQ-uncovered payment question;
- an unsupported request; and
- a prompt-injection attempt.

Each prompt was invoked in a fresh AgentCore Harness session. The generated
responses were stored in `output_eval_dataset.jsonl` using the Amazon Bedrock
bring-your-own-inference response format. Amazon Nova Pro was then used as the
LLM-as-a-judge evaluator in Amazon Bedrock Evaluations.

## Iteration observations

Early runs exposed three important failure modes. The assistant could treat a
symptom as complete reproduction steps, infer a payment policy that was not in
the FAQ, or omit the required human-support handoff for unsupported requests.
The system prompt was refined with an explicit pre-tool checklist, strict FAQ
grounding rules, deterministic fallbacks, and examples for ambiguous and
adversarial inputs. The terminal client was also updated to preserve the full
conversation and enforce the bug-intake sequence before making the ticketing
tool available.

## Final results

The final evaluation processed all seven prompts and reported:

- Correctness: **1.00**
- Completeness: **1.00**
- Harmfulness: **0.00**

These results indicate that every evaluated response matched its expected
behavior, resolved the requested task completely, and contained no harmful
content. Screenshots of the evaluation summary and metric breakdown are stored
in `screenshots/bedrock_evaluation_results1.png` through
`screenshots/bedrock_evaluation_results4.png`.
