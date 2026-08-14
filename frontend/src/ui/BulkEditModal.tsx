import React from 'react'
import {
  USAGE_CATEGORIES,
  RESTRICTION_CATEGORIES,
  USAGE_KEYS,
  RESTRICTION_KEYS,
  UsageState,
  RestrictionState,
} from '../types/rights'

type BulkUsageState = UsageState | null
type BulkRestrictionState = RestrictionState | null

type Props = {
  open: boolean
  onClose: () => void
  onApply: (payload: { changes: any; note?: string }) => void
  selectedCount: number
}

export function BulkEditModal({ open, onClose, onApply, selectedCount }: Props) {
  const [usage, setUsage] = React.useState<Record<string, BulkUsageState>>({})
  const [restrictions, setRestrictions] = React.useState<Record<string, BulkRestrictionState>>({})
  const [approvalDays, setApprovalDays] = React.useState<number | ''>('')
  const [note, setNote] = React.useState('')

  React.useEffect(() => {
    if (!open) {
      setUsage({})
      setRestrictions({})
      setApprovalDays('')
      setNote('')
    }
  }, [open])

  if (!open) return null

  const cycleUsage = (value: BulkUsageState): BulkUsageState => {
    if (value === null || value === undefined) return 'allowed'
    if (value === 'allowed') return 'requires_approval'
    if (value === 'requires_approval') return 'blocked'
    return null
  }

  const cycleRestriction = (value: BulkRestrictionState): BulkRestrictionState => {
    if (value === null || value === undefined) return 'allowed'
    if (value === 'allowed') return 'conditional'
    if (value === 'conditional') return 'denied'
    return null
  }

  function buildChanges() {
    const usageMatrix: Record<string, string> = {}
    Object.entries(usage).forEach(([key, value]) => {
      if (!value) return
      usageMatrix[key] = value
    })

    const restrictionMatrix: Record<string, string> = {}
    Object.entries(restrictions).forEach(([key, value]) => {
      if (!value) return
      restrictionMatrix[key] = value
    })

    const changes: any = {}
    if (Object.keys(usageMatrix).length) changes.usageMatrix = usageMatrix
    if (Object.keys(restrictionMatrix).length) changes.restrictionMatrix = restrictionMatrix
    if (approvalDays !== '' && !Number.isNaN(approvalDays)) {
      changes.approval = { approvalWindowDays: Number(approvalDays) }
    }
    return changes
  }

  function apply() {
    const changes = buildChanges()
    if (!Object.keys(changes).length && note === '') {
      onClose()
      return
    }
    onApply({ changes, note })
  }

  return (
    <div id="rc-bulk-modal" className="fixed inset-0 z-40 flex items-center justify-center bg-black/30 px-6">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-3xl max-h-[90vh] overflow-y-auto p-6 space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold text-gray-900">Bulk edit</h2>
            <p className="text-sm text-gray-500">Applying changes to {selectedCount} selected works</p>
          </div>
          <button className="text-sm text-gray-500 hover:text-gray-700" onClick={onClose}>Close</button>
        </div>

        <section>
          <h3 className="text-sm font-semibold text-gray-700 mb-3">Usage permissions</h3>
          <div id="rc-bulk-usage-grid" className="grid grid-cols-2 gap-3">
            {USAGE_KEYS.map(key => {
              const state = usage[key] ?? null
              const meta = USAGE_CATEGORIES[key]
              const label = state === 'allowed' ? 'allowed' : state === 'requires_approval' ? 'approval' : state === 'blocked' ? 'blocked' : 'no change'
              const classes = state === 'allowed'
                ? 'bg-green-50 border-green-400 text-green-700'
                : state === 'requires_approval'
                  ? 'bg-amber-50 border-amber-400 text-amber-700'
                  : state === 'blocked'
                    ? 'bg-red-50 border-red-400 text-red-700'
                    : 'border-gray-200 hover:border-gray-300'
              return (
                <button
                  key={key}
                  className={`flex items-center justify-between px-4 py-3 border rounded-lg text-sm ${classes}`}
                  onClick={() => setUsage(prev => ({ ...prev, [key]: cycleUsage(prev[key] ?? null) }))}
                  title={meta.description}
                >
                  <span className="font-medium">{meta.title}</span>
                  <span className="text-xs uppercase">{label}</span>
                </button>
              )
            })}
          </div>
        </section>

        <section>
          <h3 className="text-sm font-semibold text-gray-700 mb-3">Restriction policies</h3>
          <div id="rc-bulk-restriction-grid" className="grid grid-cols-2 gap-3">
            {RESTRICTION_KEYS.map(key => {
              const state = restrictions[key] ?? null
              const meta = RESTRICTION_CATEGORIES[key]
              const label = state === 'denied' ? 'denied' : state === 'conditional' ? 'conditional' : state === 'allowed' ? 'allowed' : 'no change'
              const classes = state === 'denied'
                ? 'bg-red-50 border-red-400 text-red-700'
                : state === 'conditional'
                  ? 'bg-amber-50 border-amber-400 text-amber-700'
                  : state === 'allowed'
                    ? 'bg-green-50 border-green-400 text-green-700'
                    : 'border-gray-200 hover:border-gray-300'
              return (
                <button
                  key={key}
                  className={`flex items-center justify-between px-4 py-3 border rounded-lg text-sm ${classes}`}
                  onClick={() => setRestrictions(prev => ({ ...prev, [key]: cycleRestriction(prev[key] ?? null) }))}
                  title={meta.description}
                >
                  <span className="font-medium">{meta.title}</span>
                  <span className="text-xs uppercase">{label}</span>
                </button>
              )
            })}
          </div>
        </section>

        <section className="grid grid-cols-2 gap-4">
          <div>
            <label htmlFor="rc-bulk-approval-days" className="text-sm font-medium text-gray-700">Approval window (days)</label>
            <input
              id="rc-bulk-approval-days"
              type="number"
              min={0}
              className="mt-1 w-full px-3 py-2 border border-gray-300 rounded-lg"
              value={approvalDays}
              onChange={e => setApprovalDays(e.target.value === '' ? '' : Number(e.target.value))}
            />
          </div>
          <div>
            <label htmlFor="rc-bulk-note" className="text-sm font-medium text-gray-700">Note (optional)</label>
            <input
              id="rc-bulk-note"
              type="text"
              className="mt-1 w-full px-3 py-2 border border-gray-300 rounded-lg"
              value={note}
              onChange={e => setNote(e.target.value)}
            />
          </div>
        </section>

        <div className="flex justify-end gap-3">
          <button className="px-4 py-2 text-sm text-gray-600" onClick={onClose}>Cancel</button>
          <button id="rc-bulk-apply" className="px-5 py-2 bg-blue-600 text-white rounded-lg" onClick={apply}>
            Apply changes
          </button>
        </div>
      </div>
    </div>
  )
}

