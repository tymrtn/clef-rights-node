import { describe, expect, it } from 'vitest'

import { buildRightsExportItem, hasAuthoritativeContract, restrictionColumnChecked, usageColumnChecked } from './RightsDetailPage'

describe('rights detail matrix columns', () => {
  it('maps scalar usage states to their corresponding columns', () => {
    expect(usageColumnChecked('allowed', 'allowed')).toBe(true)
    expect(usageColumnChecked('requires_approval', 'requires_approval')).toBe(true)
    expect(usageColumnChecked('blocked', 'allowed')).toBe(false)
  })

  it('maps scalar restriction states to their corresponding columns', () => {
    expect(restrictionColumnChecked('denied', 'denied')).toBe(true)
    expect(restrictionColumnChecked('conditional', 'conditional')).toBe(true)
    expect(restrictionColumnChecked('allowed', 'denied')).toBe(false)
  })
})

describe('rights export identity', () => {
  it('preserves the canonical key instead of substituting alternate identifiers or title', () => {
    const contract = { matrix: { usage: {}, restrictions: {} } }
    const item = buildRightsExportItem(
      { key: 'source:mbid-123', mlcSongCode: 'MLC-OTHER', isrc: 'US-OTHER', title: 'Home' },
      contract,
    )
    expect(item).toEqual({ key: 'source:mbid-123', rightsContract: contract })
  })
})

describe('authoritative contract gate', () => {
  const matrix = { usage: { streaming_visual: 'allowed' }, restrictions: { likeness_voice_clone: 'denied' } }

  it('rejects missing and simulated contracts', () => {
    expect(hasAuthoritativeContract(null)).toBe(false)
    expect(hasAuthoritativeContract({ matrix, metadata: { simulated: true } })).toBe(false)
  })

  it('accepts a non-simulated contract with explicit matrices', () => {
    expect(hasAuthoritativeContract({ matrix, metadata: { source: 'rights-api' } })).toBe(true)
  })
})
