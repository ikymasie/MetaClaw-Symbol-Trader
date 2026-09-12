## 2024-03-24 - Hoisting Hooks for Nested Renders
**Learning:** When attempting to optimize array filtering operations inside nested helper functions (e.g., `const renderCategory = () => { ... }`) within a React component, wrapping the inner logic with `useMemo` violates the Rules of Hooks and causes fatal runtime crashes, as the helpers are often conditionally invoked.
**Action:** Always hoist `useMemo` and other hooks to the top level of the main functional component body, passing the memoized results as variables or closure scope to the nested render helpers.
