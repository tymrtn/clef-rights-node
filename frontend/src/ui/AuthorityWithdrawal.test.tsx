import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, expect, it, vi } from "vitest";
import { AuthorityWithdrawal } from "./AuthorityWithdrawal";

let view: ReactTestRenderer;
const preview = { canWithdraw:true, expectedDigest:'a'.repeat(64), pendingRequests:2, approvedGrants:1 };
const response = (value: unknown, status=200) => new Response(JSON.stringify(value), { status });
const find = (text: string) => view.root.findAllByType('button').find(button => button.children.includes(text))!;
afterEach(() => { act(() => view?.unmount()); vi.unstubAllGlobals(); });
async function mount(fetcher: any, onChanged=vi.fn(async () => {})) {
  vi.stubGlobal('fetch',fetcher);
  await act(async () => { view = create(<AuthorityWithdrawal sessionId="synthetic" organizationId="org" claimId="claim" onChanged={onChanged} />); });
  await act(async () => { await find('Review withdrawal').props.onClick(); });
  return onChanged;
}
function fill() {
  act(() => {
    view.root.findByType('textarea').props.onChange({target:{value:'Mandate ended'}});
    view.root.findByType('input').props.onChange({target:{checked:true}});
  });
}

it('shows concrete consequences and requires a reason and confirmation', async () => {
  const fetcher=vi.fn(async (_url: string, _init: RequestInit) => response(preview));
  await mount(fetcher);
  expect(view.root.findAllByType('p')[0].children.join('')).toContain('2 pending requests');
  expect(view.root.findAllByType('p')[1].children.join('')).toContain('Issued grants: 1');
  expect(find('Withdraw authority').props.disabled).toBe(true);
  fill();
  await act(async () => { await find('Withdraw authority').props.onClick(); });
  expect(JSON.parse(fetcher.mock.calls[1][1].body as string)).toEqual({expected_digest:preview.expectedDigest,reason:'Mandate ended',confirm_withdrawal:true});
  expect(JSON.stringify(view.toJSON())).toContain('Authority withdrawn.');
});

it('keeps the same payload for an interrupted withdrawal and suppresses double clicks', async () => {
  const writes: string[]=[]; let finish!: () => void;
  const fetcher=vi.fn(async (_url,init) => {
    if(init.method==='GET') return response(preview);
    writes.push(init.body);
    if(writes.length===1) { await new Promise<void>(resolve => { finish=resolve; }); throw new Error('Connection interrupted'); }
    return response({});
  });
  await mount(fetcher); fill();
  const click=find('Withdraw authority').props.onClick;
  act(() => { click(); click(); });
  expect(writes).toHaveLength(1);
  await act(async () => { finish(); });
  expect(view.root.findByType('textarea').props.disabled).toBe(true);
  await act(async () => { await find('Retry withdrawal').props.onClick(); });
  expect(writes).toEqual([writes[0],writes[0]]);
});

it('requires a fresh preview after a concurrent authority change', async () => {
  await mount(vi.fn(async (_url,init) => init.method==='GET' ? response(preview) : response({detail:'Authority changed'},409)));
  fill(); await act(async () => { await find('Withdraw authority').props.onClick(); });
  expect(find('Review withdrawal')).toBeTruthy();
  expect(view.root.findAllByType('textarea')).toHaveLength(0);
});

it('reports successful withdrawal even when list refresh fails', async () => {
  await mount(vi.fn(async () => response(preview)),vi.fn(async () => { throw new Error('Refresh offline'); }));
  fill(); await act(async () => { await find('Withdraw authority').props.onClick(); });
  expect(JSON.stringify(view.toJSON())).toContain('Authority withdrawn. Reload');
  expect(view.root.findAllByType('button')).toHaveLength(0);
});
