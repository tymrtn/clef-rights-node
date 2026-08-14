import React from 'react'
import {
  USAGE_CATEGORIES,
  RESTRICTION_CATEGORIES,
  USAGE_KEYS,
  RESTRICTION_KEYS,
  UsageState,
  RestrictionState,
} from '../types/rights'
import { checkedJson } from '../utils/http'

type Props = {
  selection: any
  onBack: () => void
  authoritativeContract?: any | null
}

const usageStateLabels: Record<UsageState, string> = {
  allowed: 'Allowed',
  requires_approval: 'Requires Approval',
  blocked: 'Blocked',
}

const usageStateStyles: Record<UsageState, string> = {
  allowed: 'bg-green-100 text-green-700 border border-green-200',
  requires_approval: 'bg-amber-100 text-amber-700 border border-amber-200',
  blocked: 'bg-red-100 text-red-700 border border-red-200',
}

const restrictionStateLabels: Record<RestrictionState, string> = {
  allowed: 'Allowed',
  conditional: 'Conditional',
  denied: 'Denied',
}

const restrictionStateStyles: Record<RestrictionState, string> = {
  allowed: 'bg-green-100 text-green-700 border border-green-200',
  conditional: 'bg-amber-100 text-amber-700 border border-amber-200',
  denied: 'bg-red-100 text-red-700 border border-red-200',
}

export function usageColumnChecked(value: UsageState, column: 'allowed' | 'requires_approval'): boolean {
  return value === column
}

export function restrictionColumnChecked(value: RestrictionState, column: 'denied' | 'conditional'): boolean {
  return value === column
}

export function hasAuthoritativeContract(value: any): boolean {
  return Boolean(
    value &&
    value.metadata?.simulated !== true &&
    value.matrix &&
    typeof value.matrix.usage === 'object' &&
    typeof value.matrix.restrictions === 'object',
  )
}

export function buildRightsExportItem(selection: any, contract: any) {
  if (!selection?.key) throw new Error('A canonical work key is required for rights export')
  return { key: selection.key, rightsContract: contract }
}

export function RightsDetailPage({ selection, onBack, authoritativeContract }: Props) {
  const contract = hasAuthoritativeContract(authoritativeContract) ? authoritativeContract : null

  if (!selection) {
    return (
      <div id="rights-detail-no-selection" className="bg-white rounded-lg shadow-sm p-8 text-center">
        <button
          id="rights-detail-back-btn-empty"
          onClick={onBack}
          className="mb-4 px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors"
        >
          Back
        </button>
        <p className="text-gray-500">No selection.</p>
      </div>
    )
  }

  if (!contract) {
    return (
      <div id="rights-detail-unavailable" className="bg-white rounded-lg shadow-sm p-8">
        <button onClick={onBack} className="mb-4 px-4 py-2 bg-gray-100 text-gray-700 rounded-lg">← Back to Results</button>
        <h2 className="text-xl font-semibold text-gray-900">Rights Matrix</h2>
        <p className="mt-3 text-sm text-amber-800" role="status">
          No authoritative rights contract is loaded for this work. No permission is implied, and save/export actions are unavailable.
        </p>
      </div>
    )
  }

  return (
    <div id="rights-detail-page" className="space-y-6">
      <div id="rights-detail-header" className="bg-white rounded-lg shadow-sm p-6">
        <button
          id="rights-detail-back-btn"
          onClick={onBack}
          className="mb-4 px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors font-medium"
        >
          ← Back to Results
        </button>
        <h2 className="text-xl font-semibold text-gray-900 mb-3">Rights Matrix</h2>
        <div id="rights-detail-selection-info" className="bg-blue-50 border border-blue-200 rounded-lg p-4">
          <p className="text-sm text-gray-600 mb-1">Selected Work:</p>
          <p className="font-semibold text-gray-900">
            {selection.title || selection.workTitle}
          </p>
          <p className="text-sm text-gray-600 mt-1">
            {selection.artist || 'Unknown Artist'}
          </p>
        </div>
      </div>

      <div id="rights-contract-viewer" className="bg-white rounded-lg shadow-sm p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Usage Matrix</h3>
        <table className="w-full text-sm mb-6">
          <thead>
            <tr className="text-left text-gray-500">
              <th className="py-2">Usage</th>
              <th className="py-2">Allowed</th>
              <th className="py-2">Requires Approval</th>
            </tr>
          </thead>
          <tbody>
            {(Object.entries((contract?.matrix?.usage) || {}) as Array<[string, UsageState]>).map(([k, v]) => (
              <tr key={k} className="border-t border-gray-200">
                <td className="py-2 font-medium text-gray-900">{k}</td>
                <td className="py-2"><input type="checkbox" checked={usageColumnChecked(v, 'allowed')} readOnly /></td>
                <td className="py-2"><input type="checkbox" checked={usageColumnChecked(v, 'requires_approval')} readOnly /></td>
              </tr>
            ))}
          </tbody>
        </table>

        <h3 className="text-lg font-semibold text-gray-900 mb-4">Restriction Matrix</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500">
              <th className="py-2">Restriction</th>
              <th className="py-2">Denied</th>
              <th className="py-2">Conditional</th>
            </tr>
          </thead>
          <tbody>
            {(Object.entries((contract?.matrix?.restrictions) || {}) as Array<[string, RestrictionState]>).map(([k, v]) => (
              <tr key={k} className="border-t border-gray-200">
                <td className="py-2 font-medium text-gray-900">{k}</td>
                <td className="py-2"><input type="checkbox" checked={restrictionColumnChecked(v, 'denied')} readOnly /></td>
                <td className="py-2"><input type="checkbox" checked={restrictionColumnChecked(v, 'conditional')} readOnly /></td>
              </tr>
            ))}
          </tbody>
        </table>

        <details className="mt-6">
          <summary className="cursor-pointer text-gray-600">View raw contract JSON</summary>
          <pre
            id="rights-contract-json"
            className="mt-3 bg-gray-50 p-4 border border-gray-200 rounded-lg overflow-x-auto text-sm font-mono"
          >
            {JSON.stringify(contract, null, 2)}
          </pre>
        </details>
      </div>

      <div id="rights-detail-actions" className="bg-white rounded-lg shadow-sm p-6">
        <div className="flex gap-3">
          <button
            id="rights-export-json-btn"
            className="px-6 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors font-medium"
            onClick={async () => {
              const items = [buildRightsExportItem(selection, contract)]
              const res = await fetch('/api/rights/export', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(items)
              })
              const data = await checkedJson(res, 'Rights export')
              const blob = new Blob([JSON.stringify(data.items || items, null, 2)], { type: 'application/json' })
              const url = URL.createObjectURL(blob)
              const a = document.createElement('a')
              a.href = url
              a.download = 'rights_export.json'
              a.click()
              URL.revokeObjectURL(url)
            }}
          >
            Export JSON
          </button>
        </div>
      </div>
    </div>
  )
}
