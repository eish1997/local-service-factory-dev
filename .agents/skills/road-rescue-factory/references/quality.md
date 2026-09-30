# Quality scoring system

Use this system for previews, samples, generated covers, detail images, and group delivery checks. Score only after checking the hard-fail rules. A hard fail blocks delivery even when the numeric score is high.

## Hard-fail rules

- Paid generation was not authorized through the one-time license workflow.
- A required image file is missing, corrupt, or saved outside the project output layout.
- Confirmed phone numbers, storefront signboard phone numbers, required service text, or required category labels are missing, wrong, unreadable, or placed in an unapproved area.
- A real API key, private file content, QR code, watermark, readable license plate, real brand trademark, or unconfirmed business fact appears.
- The image is visibly unrelated to the project category or required role.
- The result is a poster/mockup instead of a believable local-service scene when the project requires realistic service imagery.
- Faces, hands, tools, vehicle parts, appliance parts, cables, wheels, straps, jacks, or work actions are severely malformed.

## 100-point score

1. Project fit and role accuracy, 15 points: the image matches the current project, cover/detail role, group structure, service category, and confirmed project scope.
2. Real local-service scene, 15 points: environment, shop/street/home/worksite context, people, equipment, props, and ordinary smartphone feel are believable.
3. Action and object plausibility, 15 points: repair/rescue/installation/cleaning actions, tool geometry, contact points, cables, straps, hands, wheels, appliances, and vehicles are physically coherent.
4. Text and business-fact control, 15 points: all required local overlays and storefront signboard phone numbers are readable and correct; model-generated scene text is acceptable only when intended and not misleading; unconfirmed facts do not appear.
5. Composition and post-processing readiness, 10 points: vertical framing works, key subjects are not blocked, reserved phone-strip/category/service-grid areas are usable, and overlays will not cover critical content.
6. Visual variation and non-duplication, 10 points: batch images vary in storefront, layout, camera distance, angle, people, equipment, action, weather, and scene details; no obvious reused base image across groups unless reuse is explicitly planned.
7. Technical image quality, 10 points: resolution, sharpness, lighting, color, perspective, and artifact level are acceptable for delivery.
8. Safety and privacy hygiene, 10 points: no readable plates, private identities, real logos, watermarks, QR codes, or accidental sensitive information.

## Passing thresholds

- Preview or prompt-tuning sample: 80+ points and no hard fail.
- Formal single image: 85+ points and no hard fail.
- Cover image with phone/text requirements: 90+ points, no hard fail, signboard phone present and correct, center phone strip present and correct, and text manually or OCR verified.
- Deliverable content group: every required file exists, every image has no hard fail, the cover passes its text validation, and the group average is 88+ points.

## Feedback format

Record feedback as concrete, reusable observations. Prefer “phone strip covers the mechanic's hands; reserve a lower-middle empty band” over “layout is bad.” Promote a note into a project style profile only when it is reusable across future images. Keep one-off defects in feedback or validation notes instead of long-term rules.
