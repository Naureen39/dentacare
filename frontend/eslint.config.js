import js from '@eslint/js'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import globals from 'globals'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  {
    ignores: [
      'dist',
      'dist-audit',
      'dist-server',
      'playwright-report',
      'test-results',
      'src/lib/api-types.ts',
    ],
  },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: { ecmaVersion: 2022, globals: globals.browser },
    plugins: { 'react-hooks': reactHooks, 'react-refresh': reactRefresh },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      '@typescript-eslint/consistent-type-imports': 'error',
    },
  },
  {
    // Component libraries and providers export variants, hooks and helpers beside components.
    files: [
      'src/app/routes.tsx',
      'src/components/ui/**',
      'src/lib/auth.tsx',
      'src/lib/auth-forms.tsx',
    ],
    rules: { 'react-refresh/only-export-components': 'off' },
  },
)
