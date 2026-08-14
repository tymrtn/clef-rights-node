import React from 'react'

type Props = { onConfirm: (name: string) => void }

export function ArtistGate({ onConfirm }: Props) {
  const [name, setName] = React.useState('')
  const [error, setError] = React.useState('')

  function confirm() {
    const trimmed = name.trim()
    if (!trimmed || trimmed.length < 2) {
      setError('Please enter your artist name')
      return
    }
    onConfirm(trimmed)
  }

  return (
    <div id="rc-artist-gate" className="bg-white rounded-lg shadow-sm p-6 max-w-xl">
      <h2 className="text-xl font-semibold text-gray-900 mb-2">Select Your Artist Profile</h2>
      <p className="text-gray-600 mb-4">Enter your artist name. Your session will be scoped to this artist’s catalog for the demo.</p>
      <div className="flex gap-2">
        <input id="rc-artist-name" className="flex-1 px-4 py-2 border border-gray-300 rounded-lg" placeholder="Artist name" value={name} onChange={e => setName(e.target.value)} />
        <button id="rc-artist-confirm" className="px-4 py-2 bg-blue-600 text-white rounded-lg" onClick={confirm}>Continue</button>
      </div>
      {error && <div className="text-red-600 text-sm mt-2">{error}</div>}
    </div>
  )
}

