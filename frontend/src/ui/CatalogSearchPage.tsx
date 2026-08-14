import React from 'react'
import { checkedJson } from '../utils/http'

type Props = {
  onSelect: (row: any) => void
  artistName?: string | null
}

export function CatalogSearchPage({ onSelect, artistName }: Props) {
  const [artist, setArtist] = React.useState(artistName || '')
  const [title, setTitle] = React.useState('')
  const [publisher, setPublisher] = React.useState('')
  const [writer, setWriter] = React.useState('')
  const [results, setResults] = React.useState<any[]>([])
  const [loading, setLoading] = React.useState(false)
  const [validationError, setValidationError] = React.useState('')
  const [searchError, setSearchError] = React.useState('')

  const canSearch = title || writer || publisher || (artist && title)
  const hasRecordingsSearch = artist && title
  const hasSongcodeSearch = title || writer || publisher

  async function search() {
    setValidationError('')
    setSearchError('')

    // Validate search criteria
    if (!title && !writer && !publisher) {
      setValidationError('Please enter at least: Title, Songwriter, or Publisher')
      return
    }

    setLoading(true)
    try {
      let rows: any[] = []

      // MLC recordings API requires both artist AND title
      if (artist && title) {
        const res = await fetch('/api/mlc/search/recordings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Artist-Name': artistName || '' },
          body: JSON.stringify({ artist, title })
        })
        const data = await checkedJson(res, 'Recording search')
        rows = data.results || []
      }

      // Songcode search (works with title, writer, publisher)
      if (title || writer || publisher) {
        const sc = await fetch('/api/mlc/search/songcode', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Artist-Name': artistName || '' },
          body: JSON.stringify({ title, writer_lastname: writer, publisher })
        })
        const scData = await checkedJson(sc, 'Song-code search')
        rows = [...rows, ...(scData.results || [])]
      }

      setResults(rows)
    } catch (error) {
      setSearchError(error instanceof Error ? error.message : 'Catalog search failed')
    } finally {
      setLoading(false)
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !loading && canSearch) {
      search()
    }
  }

  return (
    <div id="catalog-search-page" className="space-y-6">
      <div id="search-header" className="bg-white rounded-lg shadow-sm p-6">
        <h2 className="text-xl font-semibold text-gray-900 mb-4">MLC Catalog Search</h2>

        {/* Search constraints info */}
        <div id="search-info" className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
          <p className="text-sm text-blue-800">
            <strong>Search Requirements:</strong> Enter at least Title, Songwriter, or Publisher.
            {artist && !title && <span className="ml-2 text-blue-600">• Add Title for recordings search</span>}
          </p>
        </div>

        <div id="search-form" className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div id="artist-field-wrapper">
              <label htmlFor="search-artist-input" className="block text-sm font-medium text-gray-700 mb-1">
                Artist {artistName && <span className="text-gray-500">(locked)</span>}
              </label>
              <input
                id="search-artist-input"
                type="text"
                placeholder="Artist name"
                value={artist}
                onChange={e => setArtist(e.target.value)}
                onKeyPress={handleKeyPress}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none disabled:bg-gray-100 disabled:cursor-not-allowed"
                disabled={!!artistName}
              />
            </div>

            <div id="title-field-wrapper">
              <label htmlFor="search-title-input" className="block text-sm font-medium text-gray-700 mb-1">
                Title {artist && <span className="text-blue-600 text-xs">(required for recordings)</span>}
              </label>
              <input
                id="search-title-input"
                type="text"
                placeholder="Song or work title"
                value={title}
                onChange={e => setTitle(e.target.value)}
                onKeyPress={handleKeyPress}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
              />
            </div>

            <div id="publisher-field-wrapper">
              <label htmlFor="search-publisher-input" className="block text-sm font-medium text-gray-700 mb-1">
                Publisher
              </label>
              <input
                id="search-publisher-input"
                type="text"
                placeholder="Publisher name"
                value={publisher}
                onChange={e => setPublisher(e.target.value)}
                onKeyPress={handleKeyPress}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
              />
            </div>

            <div id="writer-field-wrapper">
              <label htmlFor="search-writer-input" className="block text-sm font-medium text-gray-700 mb-1">
                Songwriter (Last Name)
              </label>
              <input
                id="search-writer-input"
                type="text"
                placeholder="Writer last name"
                value={writer}
                onChange={e => setWriter(e.target.value)}
                onKeyPress={handleKeyPress}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
              />
            </div>
          </div>

          {/* Validation error */}
          {validationError && (
            <div id="search-validation-error" className="p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-sm text-red-700">{validationError}</p>
            </div>
          )}
          {searchError && (
            <div id="search-request-error" className="p-3 bg-red-50 border border-red-200 rounded-lg" role="alert">
              <p className="text-sm text-red-700">{searchError}</p>
            </div>
          )}

          {/* Search indicators */}
          {canSearch && (
            <div id="search-indicators" className="flex gap-2 flex-wrap">
              {hasRecordingsSearch && (
                <span className="px-3 py-1 bg-green-100 text-green-700 text-xs font-medium rounded-full">
                  Recordings Search
                </span>
              )}
              {hasSongcodeSearch && (
                <span className="px-3 py-1 bg-purple-100 text-purple-700 text-xs font-medium rounded-full">
                  Songcode Search
                </span>
              )}
            </div>
          )}

          <button
            id="search-submit-btn"
            onClick={search}
            disabled={loading || !canSearch}
            className={`w-full md:w-auto px-6 py-2 rounded-lg font-medium transition-colors ${
              loading || !canSearch
                ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                : 'bg-blue-600 text-white hover:bg-blue-700'
            }`}
          >
            {loading ? 'Searching...' : 'Search'}
          </button>
        </div>
      </div>

      <div id="search-results" className="bg-white rounded-lg shadow-sm">
        {results.length === 0 ? (
          <div id="search-results-empty" className="p-8 text-center text-gray-500">
            {loading ? 'Loading...' : 'Enter title, songwriter, or publisher to search The MLC catalog. For recordings search, enter both artist and title.'}
          </div>
        ) : (
          <ul id="search-results-list" className="divide-y divide-gray-200">
            {results.map((r, idx) => (
              <li
                key={idx}
                id={`search-result-item-${idx}`}
                className="p-4 hover:bg-gray-50 cursor-pointer transition-colors"
                onClick={() => onSelect(r)}
              >
                <div className="font-semibold text-gray-900">
                  {r.title || r.workTitle}
                </div>
                <div className="text-sm text-gray-600 mt-1">
                  {r.artist || 'Unknown Artist'}
                  {r.isrc && <span className="ml-2 text-gray-400">· ISRC {r.isrc}</span>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
