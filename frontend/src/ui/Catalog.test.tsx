import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Catalog } from "./RightsNodeApp";

const session = { id: "synthetic-session", email: "reviewer@example.test", expires_at: "2027-01-01" };
const organization = { id: "org-1", name: "Fictional label" } as any;
const clients = [
  { id: "artist-1", name: "Fictional artist", externalReference: "fixture-1" },
  { id: "artist-2", name: "Other fictional artist", externalReference: "fixture-2" },
];
const asset = { id: "recording-1", title: "Fictional song", workKey: "isrc:ZZDEM0000001", artist: "Fictional artist", itemType: "recording", territory: "US", version: 1, client: clients[0] };
const ok = (body: unknown) => new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
let view: ReactTestRenderer | undefined;
afterEach(() => { if (view) act(() => view!.unmount()); view = undefined; vi.unstubAllGlobals(); });
const button = (label: string) => view!.root.findAllByType("button").find(item => item.children.includes(label))!;

describe("catalog assignment through the rendered controls", () => {
  it.each([
    { select: undefined, expected: "artist-1", description: "retains the displayed client when the selector is untouched" },
    { select: "", expected: null, description: "unassigns only when Unassigned is explicitly selected" },
    { select: "artist-2", expected: "artist-2", description: "uses the newly selected client" },
  ])("$description", async ({ select, expected }) => {
    const writes: any[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url, init) => {
      if (init?.method === "POST") { writes.push(JSON.parse(init.body)); return ok({}); }
      return ok(String(url).endsWith("/clients") ? { clients } : String(url).endsWith("/assets") ? { assets: [asset] } : { imports: [] });
    }));
    await act(async () => { view = create(<Catalog session={session} organization={organization} />); });
    expect(view!.root.findByProps({ "aria-label": "Managed client for Fictional song" }).props.value).toBe("artist-1");
    if (select !== undefined) act(() => view!.root.findByProps({ "aria-label": "Managed client for Fictional song" }).props.onChange({ target: { value: select } }));
    act(() => view!.root.findByProps({ "aria-label": "Assignment reason for Fictional song" }).props.onChange({ target: { value: "Fictional administration review" } }));
    await act(async () => { await button("Append assignment").props.onClick(); });
    expect(writes).toEqual([{ client_id: expected, reason: "Fictional administration review" }]);
  });
});

const staged = (id: string, digest = id.repeat(64).slice(0,64)) => ({
  id, filename:`${id}.csv`, fileSha256:'f'.repeat(64), previewDigest:digest, status:'preview', rows:[],
  summary:{ total:1, unresolved:0, importable:1, skipped:0, counts:{ready:1} },
});
const importButton = (name: string) => view!.root.findAllByType('button').find(item =>
  item.findAllByType('strong').some(strong => strong.children.includes(name)))!;

describe('catalog preview recovery', () => {
  it('refreshes the reviewed snapshot and clears prior import confirmation', async () => {
    const first=staged('a'); const refreshed=staged('a','b'.repeat(64)); const writes: any[]=[];
    vi.stubGlobal('fetch',vi.fn(async (url,init) => {
      if(init?.method==='POST') { writes.push(JSON.parse(init.body)); return ok(refreshed); }
      if(String(url).endsWith('/imports/a')) return ok(first);
      return ok(String(url).endsWith('/imports') ? {imports:[first]} : String(url).endsWith('/clients') ? {clients:[]} : {assets:[]});
    }));
    await act(async () => { view=create(<Catalog session={session} organization={organization} />); });
    await act(async () => { await importButton('a.csv').props.onClick(); });
    act(() => view!.root.findAllByProps({type:'checkbox'})[0].props.onChange({target:{checked:true}}));
    expect(button('Commit catalog').props.disabled).toBe(false);
    await act(async () => { await button('Refresh preview').props.onClick(); });
    expect(writes).toEqual([{expected_preview_digest:first.previewDigest}]);
    expect(button('Commit catalog').props.disabled).toBe(true);
    act(() => view!.root.findAllByProps({type:'checkbox'})[0].props.onChange({target:{checked:true}}));
    await act(async () => { await button('Commit catalog').props.onClick(); });
    expect(writes[1]).toEqual({confirm_import:true,expected_preview_digest:refreshed.previewDigest});
  });

  it('keeps the latest chosen preview when an earlier request finishes late', async () => {
    let finish!: (value: Response) => void;
    const a=staged('a'); const b=staged('b');
    vi.stubGlobal('fetch',vi.fn(async url => {
      if(String(url).endsWith('/imports/a')) return new Promise<Response>(resolve => { finish=resolve; });
      if(String(url).endsWith('/imports/b')) return ok(b);
      return ok(String(url).endsWith('/imports') ? {imports:[a,b]} : String(url).endsWith('/clients') ? {clients:[]} : {assets:[]});
    }));
    await act(async () => { view=create(<Catalog session={session} organization={organization} />); });
    act(() => { importButton('a.csv').props.onClick(); });
    await act(async () => { await importButton('b.csv').props.onClick(); });
    await act(async () => { finish(ok(a)); });
    expect(JSON.stringify(view!.toJSON())).toContain('3. Review b.csv');
    expect(JSON.stringify(view!.toJSON())).not.toContain('3. Review a.csv');
  });

  it('retries an interrupted commit with the same review digest and suppresses double clicks', async () => {
    const a=staged('a'); const writes: string[]=[]; let finish!: () => void;
    vi.stubGlobal('fetch',vi.fn(async (url,init) => {
      if(init?.method==='POST') {
        writes.push(init.body);
        if(writes.length===1) { await new Promise<void>(resolve => { finish=resolve; }); throw new Error('Response interrupted'); }
        return ok({...a,status:'committed',summary:{...a.summary,counts:{imported:1}}});
      }
      if(String(url).endsWith('/imports/a')) return ok(a);
      return ok(String(url).endsWith('/imports') ? {imports:[a]} : String(url).endsWith('/clients') ? {clients:[]} : {assets:[]});
    }));
    await act(async () => { view=create(<Catalog session={session} organization={organization} />); });
    await act(async () => { await importButton('a.csv').props.onClick(); });
    act(() => view!.root.findAllByProps({type:'checkbox'})[0].props.onChange({target:{checked:true}}));
    const click=button('Commit catalog').props.onClick;
    act(() => { click(); click(); });
    expect(writes).toHaveLength(1);
    await act(async () => { finish(); });
    await act(async () => { await button('Commit catalog').props.onClick(); });
    expect(writes).toEqual([writes[0],writes[0]]);
    expect(JSON.stringify(view!.toJSON())).toContain('1 catalog records committed.');
  });
});
