## 2024-08-15 - [DeployWizard Symbol Filtering]
**Learning:** Filtering large datasets on every render in functional components (such as `symbolsData?.symbols.filter(...)` with string matching) causes unnecessary O(N) operations which can be expensive, especially with hundreds of elements.
**Action:** Wrap the computation in `useMemo` with appropriate dependencies to prevent unnecessary recalculations across renders.
