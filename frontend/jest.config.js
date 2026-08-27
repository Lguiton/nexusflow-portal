const nextJest = require('next/jest')

const createJestConfig = nextJest({
  dir: './',
})

/** @type {import('jest').Config} */
const customJestConfig = {
  setupFilesAfterEnv: ['<rootDir>/jest.setup.ts'],
  testEnvironment: 'jest-environment-jsdom',
  testPathIgnorePatterns: [
    '<rootDir>/node_modules/',
    '<rootDir>/.next/',
    '<rootDir>/_to_delete/',
    // AUTH-06 found this real gap: e2e/*.spec.ts are Playwright specs (run
    // via `npm run e2e`, see package.json), not Jest ones -- they import
    // '@playwright/test', whose own test() global collides with Jest's
    // when Jest tries to load them directly, so `npx jest` was always
    // reporting these 2 suites as hard failures ("Class extends value
    // undefined") rather than actually running or skipping them.
    '<rootDir>/e2e/',
  ],
  // _to_delete/ holds leftover scratch copies (from earlier tsc-check
  // workflows) that include their own duplicate package.json/node_modules
  // -- without excluding them here, Jest's haste module map sees two
  // "frontend" packages and refuses to start at all.
  modulePathIgnorePatterns: ['<rootDir>/_to_delete/'],
  watchPathIgnorePatterns: ['<rootDir>/_to_delete/'],
}

module.exports = createJestConfig(customJestConfig)
