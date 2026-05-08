# Real FDA Recall Fixtures (openFDA)

These are raw `food/enforcement` records downloaded from openFDA for offline ingestion tests.

## Intentional Malformations

The following fixtures are intentionally malformed (missing fields / weird formats / embedded HTML) to test schema robustness:
- `01_F-0399-2025.json`
- `02_F-0729-2025.json`
- `03_H-0270-2026.json`
- `04_H-0030-2025.json`
- `05_H-0286-2026.json`

## Index

| File | Recall # | Class | Hazard Type | Severity | Flags | Reason (truncated) |
|---|---|---|---|---|---|---|
| `01_F-0399-2025.json` | F-0399-2025 | Class I | salmonella | critical | lot-codes, MALFORMED | Cucumbers have the potential to be contaminated with Salmonella |
| `02_F-0729-2025.json` | F-0729-2025 | Class I | allergen | critical | allergen/undeclared, lot-codes, limited-info, MALFORMED | Undeclared allergen: Wheat |
| `03_H-0270-2026.json` | H-0270-2026 | Class I | salmonella | critical | lot-codes, limited-info, MALFORMED | Product tested positive Salmonella . |
| `04_H-0030-2025.json` | H-0030-2025 | Class I | salmonella | critical | lot-codes, limited-info, MALFORMED | Potential Salmonella Contamination |
| `05_H-0286-2026.json` | H-0286-2026 | Class I | salmonella | critical | lot-codes, limited-info, MALFORMED | Product tested positive Salmonella . |
| `06_H-0552-2026.json` | H-0552-2026 | Class II | undeclared_ingredient | high | allergen/undeclared | Inaccurate nutritional data in Nutrition Facts including but not limited to, understated sodium content. Undeclared ingr |
| `07_F-0801-2025.json` | F-0801-2025 | Class II | allergen | high | allergen/undeclared | Contains undeclared almonds & undeclared sesame |
| `08_H-0076-2025.json` | H-0076-2025 | Class II | allergen | high | allergen/undeclared, lot-codes, limited-info | Undeclared  wheat allergens |
| `09_H-0254-2025.json` | H-0254-2025 | Class II | allergen | high | allergen/undeclared, limited-info | Undeclared soy and wheat |
| `10_H-0255-2025.json` | H-0255-2025 | Class II | allergen | high | allergen/undeclared, limited-info | Undeclared wheat |
| `11_H-0417-2026.json` | H-0417-2026 | Class II | allergen | high | allergen/undeclared, lot-codes, limited-info | Undeclared wheat. |
| `12_H-0193-2026.json` | H-0193-2026 | Class I | ecoli | critical | allergen/undeclared | Raw milk Whatcom Blue cheese is recalled due to E. coli O103:H2. |
| `13_H-0191-2026.json` | H-0191-2026 | Class I | allergen | critical | allergen/undeclared, lot-codes, limited-info | Undeclared peanut. |
| `14_H-0458-2025.json` | H-0458-2025 | Class II | allergen | high | allergen/undeclared | Product label includes the ingredient CREAM but does not include Milk as the source. |
| `15_H-0389-2026.json` | H-0389-2026 | Class II | other | high | limited-info | Product tested high for lead. |
| `16_F-0543-2025.json` | F-0543-2025 | Class II | foreign_object | high | limited-info | may contain metal pieces |
| `17_H-0245-2025.json` | H-0245-2025 | Class II | other | high | lot-codes, limited-info | May be contaminated with fluid from a reach truck |
| `18_H-0088-2025.json` | H-0088-2025 | Class II | undeclared_ingredient | high | lot-codes | Product has a misbranded Yellow Color.  Identified on label at  Artificial Yellow Color , and it should be identified as |
| `19_F-0206-2025.json` | F-0206-2025 | Class II | listeria | high |  | potential to be contaminated with Listeria monocytogenes |
| `20_H-0366-2026.json` | H-0366-2026 | Class II | other | high | lot-codes, limited-info | Contains elevated levels of hydrocyanic acid |
| `21_F-0379-2025.json` | F-0379-2025 | Class I | salmonella | critical | lot-codes, limited-info | potential for salmonella |
| `22_F-0362-2025.json` | F-0362-2025 | Class I | salmonella | critical |  | Salmonella. Beef & Lamb Gyro Sandwich Express Meal Kit contains implicated cucumber in the tzatziki sauce 3oz. cup. |
| `23_H-0090-2026.json` | H-0090-2026 | Class I | listeria | critical |  | Salad Kits are recalled due to potential contamination with Listeria monocytogenes. |
| `24_H-0272-2026.json` | H-0272-2026 | Class I | salmonella | critical | lot-codes, limited-info | Product tested positive Salmonella . |
| `25_H-0264-2025.json` | H-0264-2025 | Class I | listeria | critical |  | Potential to be contaminated with Listeria monocytogenes |
