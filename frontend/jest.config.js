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
  ],
  // _to_delete/ holds leftover scratch copies (from earlier tsc-check
  // workflows) that include their own duplicate package.json/node_modules
  // -- without excluding them here, Jest's haste module map sees two
  // "frontend" packages and refuses to start at all.
  modulePathIgnorePatterns: ['<rootDir>/_to_delete/'],
  watchPathIgnorePatterns: ['<rootDir>/_to_delete/'],
}

module.exports = createJestConfig(customJestConfig)
