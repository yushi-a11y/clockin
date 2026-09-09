#!/usr/bin/env python3
"""Targeted regression tests for picks ID normalization and cross-day punch matching."""

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = "http://127.0.0.1:8766/index.html"


async def main():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        async def route_request(route):
            url = route.request.url
            blocked = (
                "fonts.googleapis.com", "fonts.gstatic.com", "www.gstatic.com",
                "firestore.googleapis.com", "firebase.googleapis.com", "supabase"
            )
            if any(host in url for host in blocked):
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", route_request)
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_function("() => typeof normalizePicksData === 'function'", timeout=15000)

        normalized = await page.evaluate("""() => normalizePicksData({
            '2026-08-01': { 14: ['25', '7', 7, 'bad'] },
            invalid: { 14: [7] }
        })""")
        assert normalized == {"2026-08-01": {"14": [7, 25]}}, normalized

        stats = await page.evaluate("""() => {
            picks = normalizePicksData({
                '2026-08-01': { 14: ['7', '25'] },
                '2026-08-02': { '14': ['7'] }
            });
            picksLocalVer = Date.now();
            _invalidateMonthCache();
            const member = { id: 14, name: '成员14', dept: '测试' };
            return {
                shifts: memberShifts(member, '2026-08-01'),
                month: memberMonthShiftCount(14, '2026-08'),
                total: memberMonthValid(14, '2026-08')
            };
        }""")
        assert stats["shifts"] == [7, 25], stats
        assert stats["month"] == {"am": 2, "pm": 1}, stats
        assert stats["total"] == 3, stats

        historical_sid_metrics = await page.evaluate("""() => {
            const old = {
                picks, shifts: state.shifts, punches: state.punches,
                leaves, makeups, fbPunches
            };
            try {
                state.shifts = [{
                    id: 7, name: '07:00-08:00', start: '07:00', end: '08:00',
                    tolerance: 5, enabled: true, cross: false
                }];
                state.punches = {};
                fbPunches = [];
                picks = { '2026-08-10': { '14': ['7'] } };
                leaves = [{
                    id: 'lv1', mid: '14', date: '2026-08-10',
                    sids: ['7'], status: 'approved'
                }];
                makeups = [];
                const leaveCovered = calcMonthMetrics(14, '2026-08');

                leaves = [];
                makeups = [
                    { id: 'mk1', mid: '14', date: '2026-08-10', sid: '7', t: 's', status: 'accepted' },
                    { id: 'mk2', mid: '14', date: '2026-08-10', sid: '7', t: 'e', status: 'accepted' }
                ];
                const makeupCovered = calcMonthMetrics(14, '2026-08');
                return { leaveCovered, makeupCovered };
            } finally {
                picks = old.picks;
                state.shifts = old.shifts;
                state.punches = old.punches;
                leaves = old.leaves;
                makeups = old.makeups;
                fbPunches = old.fbPunches;
            }
        }""")
        assert historical_sid_metrics["leaveCovered"]["missCount"] == 0, historical_sid_metrics
        assert historical_sid_metrics["makeupCovered"]["missCount"] == 0, historical_sid_metrics

        normalized_related_data = await page.evaluate("""() => ({
            shifts: normalizeShiftsData([{ id: '23', name: '夜班' }]),
            swaps: normalizeSwapsData([{
                id: 'sw1', fromId: 14, toId: '15', sid: '23',
                exchange: { takeDate: '2026-08-02', takeSid: '7' }
            }])
        })""")
        assert normalized_related_data["shifts"][0]["id"] == 23, normalized_related_data
        normalized_swap = normalized_related_data["swaps"][0]
        assert normalized_swap["fromId"] == "14", normalized_swap
        assert normalized_swap["toId"] == "15", normalized_swap
        assert normalized_swap["sid"] == 23, normalized_swap
        assert normalized_swap["exchange"]["takeSid"] == 7, normalized_swap

        validation = await page.evaluate("""() => ({
            valid: validatePicksStructure({ '2026-08-01': { '14': ['7', 25] } }),
            invalidDate: validatePicksStructure({ unexpected: { '14': [7] } }),
            invalidMemberData: validatePicksStructure({ '2026-08-01': { '14': '7' } }),
            invalidSid: validatePicksStructure({ '2026-08-01': { '14': ['bad'] } })
        })""")
        assert validation == {
            "valid": True, "invalidDate": False,
            "invalidMemberData": False, "invalidSid": False
        }, validation

        offline_atomic = await page.evaluate("""async () => {
            const oldReady = fbReady;
            fbReady = false;
            picks = { '2026-08-03': { '14': ['7', 25] } };
            const removed = await atomicRemovePick('2026-08-03', 14, '7');
            const added = await atomicAddPick('2026-08-03', 14, '23');
            const addRemoveValue = picks['2026-08-03']['14'].slice();

            picks = { '2026-08-04': { '1': ['7'], '2': ['8'] } };
            const exchanged = await atomicExchangePicks('2026-08-04', 1, '7', '2026-08-04', 2, '8');
            const exchangedAgain = await atomicExchangePicks('2026-08-04', 1, '7', '2026-08-04', 2, '8');
            const exchangeValue = JSON.parse(JSON.stringify(picks['2026-08-04']));

            picks = { '2026-08-05': { '1': ['7'], '2': [] } };
            const transferred = await atomicTransferPick('2026-08-05', 1, 2, '7');
            const transferredAgain = await atomicTransferPick('2026-08-05', 1, 2, '7');
            const transferValue = JSON.parse(JSON.stringify(picks['2026-08-05']));
            fbReady = oldReady;
            return { removed, added, addRemoveValue, exchanged, exchangedAgain, exchangeValue, transferred, transferredAgain, transferValue };
        }""")
        assert offline_atomic["removed"] is True and offline_atomic["added"] is True, offline_atomic
        assert offline_atomic["addRemoveValue"] == [23, 25], offline_atomic
        assert offline_atomic["exchanged"]["ok"] is True, offline_atomic
        assert offline_atomic["exchangedAgain"] == {"ok": True, "alreadyApplied": True}, offline_atomic
        assert offline_atomic["exchangeValue"] == {"1": [8], "2": [7]}, offline_atomic
        assert offline_atomic["transferred"]["ok"] is True, offline_atomic
        assert offline_atomic["transferredAgain"] == {"ok": True, "alreadyApplied": True}, offline_atomic
        assert offline_atomic["transferValue"] == {"1": [], "2": [7]}, offline_atomic

        offline_capacity = await page.evaluate("""async () => {
            const oldReady = fbReady, oldPicks = picks, oldCaps = slotCap;
            try {
                fbReady = false;
                picks = { '2026-08-05': { '1': [7], '2': [] } };
                slotCap = { '2026-08-05': { '7': 1 } };
                const optimisticOwner = await atomicAddPickCap('2026-08-05', 1, 7, false);
                const blockedSecondMember = await atomicAddPickCap('2026-08-05', 2, 7, false);
                return { optimisticOwner, blockedSecondMember };
            } finally {
                fbReady = oldReady;
                picks = oldPicks;
                slotCap = oldCaps;
            }
        }""")
        assert offline_capacity["optimisticOwner"]["ok"] is True, offline_capacity
        assert offline_capacity["blockedSecondMember"]["reason"] == "full", offline_capacity

        firestore_idempotency = await page.evaluate("""async () => {
            const docs = {
                picks: { data: { '2026-08-06': { '14': ['7'] } } },
                slotcap: { data: { '2026-08-06': { '7': 1 } } }
            };
            let writes = 0;
            const provider = Object.create(_FSProvider.prototype);
            provider._fs = {
                collection: () => ({ doc: id => ({ id }) }),
                runTransaction: async fn => fn({
                    get: async ref => ({ exists: !!docs[ref.id], data: () => docs[ref.id] }),
                    set: (ref, value) => { writes++; docs[ref.id] = { ...(docs[ref.id] || {}), ...value }; }
                })
            };
            const args = {
                p_date: '2026-08-06', p_mid: '14', p_sid: '7', p_admin: false
            };
            const first = await provider.rpc('pick_add_cap', args);
            const second = await provider.rpc('pick_add_cap', args);
            return { first, second, picks: docs.picks.data, writes };
        }""")
        assert firestore_idempotency["first"]["error"] is None, firestore_idempotency
        assert firestore_idempotency["second"]["error"] is None, firestore_idempotency
        assert firestore_idempotency["picks"]["2026-08-06"]["14"] == [7], firestore_idempotency
        assert firestore_idempotency["writes"] == 1, firestore_idempotency

        malformed_sync = await page.evaluate("""async () => {
            const oldSupa = supa, oldReady = fbReady, oldVersion = picksLocalVer;
            let uploaded = null;
            picks = { '2026-08-06': { '14': [7] } };
            picksLocalVer = 1;
            fbReady = true;
            supa = {
                from: table => {
                    if (table === 'logs') return { insert: () => Promise.resolve({ error: null }) };
                    return {
                        select: fields => ({
                            eq: () => ({
                                maybeSingle: async () => fields === 'updated_at'
                                    ? { data: { updated_at: 10000 } }
                                    : { data: { id: 'picks', data: { unexpected: { '14': [7] } } } }
                            })
                        }),
                        upsert: async row => { uploaded = JSON.parse(JSON.stringify(row.data)); return { data: row, error: null }; }
                    };
                }
            };
            try {
                await syncPicks();
                return { local: JSON.parse(JSON.stringify(picks)), uploaded };
            } finally {
                supa = oldSupa;
                fbReady = oldReady;
                picksLocalVer = oldVersion;
            }
        }""")
        assert malformed_sync["local"] == {"2026-08-06": {"14": [7]}}, malformed_sync
        # syncPicks 已改为只回拉权威快照；RPC 异常时不得整包上传本地缓存覆盖云端。
        assert malformed_sync["uploaded"] is None, malformed_sync

        firestore_swap_transactions = await page.evaluate("""async () => {
            const makeProvider = initialDocs => {
                const docs = JSON.parse(JSON.stringify(initialDocs));
                let writes = 0;
                const provider = Object.create(_FSProvider.prototype);
                provider._fs = {
                    collection: () => ({ doc: id => ({ id }) }),
                    runTransaction: async fn => fn({
                        get: async ref => ({
                            exists: Object.prototype.hasOwnProperty.call(docs, ref.id),
                            data: () => JSON.parse(JSON.stringify(docs[ref.id]))
                        }),
                        set: (ref, value) => {
                            writes++;
                            docs[ref.id] = { ...(docs[ref.id] || {}), ...JSON.parse(JSON.stringify(value)) };
                        }
                    })
                };
                return { provider, docs, writeCount: () => writes };
            };

            const transferMock = makeProvider({
                picks: { data: { '2026-08-07': { '14': ['7'], '15': [] } } },
                slotcap: { data: { '2026-08-07': { '7': 1 } } }
            });
            const transferArgs = {
                p_date: '2026-08-07', p_from_mid: 14, p_to_mid: '15', p_sid: '7'
            };
            const transferFirst = await transferMock.provider.rpc('pick_transfer', transferArgs);
            const transferSecond = await transferMock.provider.rpc('pick_transfer', transferArgs);

            const exchangeMock = makeProvider({
                picks: { data: {
                    '2026-08-08': { '14': ['7'], '15': [] },
                    '2026-08-09': { '14': [], '15': ['8'] }
                } },
                slotcap: { data: {
                    '2026-08-08': { '7': 1 },
                    '2026-08-09': { '8': 1 }
                } }
            });
            const exchangeArgs = {
                p_give_date: '2026-08-08', p_giver_mid: 14, p_give_sid: '7',
                p_take_date: '2026-08-09', p_receiver_mid: '15', p_take_sid: '8'
            };
            const exchangeFirst = await exchangeMock.provider.rpc('pick_exchange', exchangeArgs);
            const exchangeSecond = await exchangeMock.provider.rpc('pick_exchange', exchangeArgs);

            const addDayFullMock = makeProvider({
                picks: { data: { '2026-08-15': { '14': [1, 2, 3, 4, 5, 6, 7] } } },
                slotcap: { data: {} }
            });
            const addDayFull = await addDayFullMock.provider.rpc('pick_add_cap', {
                p_date: '2026-08-15', p_mid: '14', p_sid: 8, p_admin: false
            });

            const addWeekFullMock = makeProvider({
                picks: { data: {
                    '2026-08-22': { '14': [1, 2, 3, 4, 5, 6] },
                    '2026-08-23': { '14': [1, 2, 3, 4, 5, 6, 7] },
                    '2026-08-24': { '14': [1, 2, 3, 4, 5, 6, 7] },
                    '2026-08-25': { '14': [1, 2, 3, 4, 5, 6, 7] },
                    '2026-08-26': { '14': [1, 2, 3, 4, 5, 6, 7] },
                    '2026-08-27': { '14': [1, 2, 3, 4, 5, 6, 7] },
                    '2026-08-28': { '14': [1, 2, 3, 4, 5, 6, 7, 8] }
                } },
                slotcap: { data: {} }
            });
            const addWeekFull = await addWeekFullMock.provider.rpc('pick_add_cap', {
                p_date: '2026-08-22', p_mid: '14', p_sid: 9, p_admin: false
            });

            const transferDayFullMock = makeProvider({
                picks: { data: { '2026-08-29': {
                    '14': [20], '15': [1, 2, 3, 4, 5, 6, 7]
                } } },
                slotcap: { data: {} }
            });
            const transferDayFull = await transferDayFullMock.provider.rpc('pick_transfer', {
                p_date: '2026-08-29', p_from_mid: '14', p_to_mid: '15', p_sid: 20
            });

            const exchangeDayFullMock = makeProvider({
                picks: { data: {
                    '2026-08-29': { '14': [20], '15': [1, 2, 3, 4, 5, 6, 7] },
                    '2026-08-30': { '14': [], '15': [8] }
                } },
                slotcap: { data: {} }
            });
            const exchangeDayFull = await exchangeDayFullMock.provider.rpc('pick_exchange', {
                p_give_date: '2026-08-29', p_giver_mid: '14', p_give_sid: 20,
                p_take_date: '2026-08-30', p_receiver_mid: '15', p_take_sid: 8
            });

            return {
                transferFirst, transferSecond,
                transferPicks: transferMock.docs.picks.data,
                transferWrites: transferMock.writeCount(),
                exchangeFirst, exchangeSecond,
                exchangePicks: exchangeMock.docs.picks.data,
                exchangeWrites: exchangeMock.writeCount(),
                addDayFull, addDayFullWrites: addDayFullMock.writeCount(),
                addWeekFull, addWeekFullWrites: addWeekFullMock.writeCount(),
                transferDayFull, transferDayFullWrites: transferDayFullMock.writeCount(),
                exchangeDayFull, exchangeDayFullWrites: exchangeDayFullMock.writeCount()
            };
        }""")
        assert firestore_swap_transactions["transferFirst"]["data"]["ok"] is True, firestore_swap_transactions
        assert firestore_swap_transactions["transferSecond"]["data"]["alreadyApplied"] is True, firestore_swap_transactions
        assert firestore_swap_transactions["transferPicks"]["2026-08-07"] == {"14": [], "15": [7]}, firestore_swap_transactions
        assert firestore_swap_transactions["transferWrites"] == 1, firestore_swap_transactions
        assert firestore_swap_transactions["exchangeFirst"]["data"]["ok"] is True, firestore_swap_transactions
        assert firestore_swap_transactions["exchangeSecond"]["data"]["alreadyApplied"] is True, firestore_swap_transactions
        assert firestore_swap_transactions["exchangePicks"] == {
            "2026-08-08": {"14": [], "15": [7]},
            "2026-08-09": {"14": [8], "15": []},
        }, firestore_swap_transactions
        assert firestore_swap_transactions["exchangeWrites"] == 1, firestore_swap_transactions
        assert firestore_swap_transactions["addDayFull"]["data"]["reason"] == "dayfull", firestore_swap_transactions
        assert firestore_swap_transactions["addDayFullWrites"] == 0, firestore_swap_transactions
        assert firestore_swap_transactions["addWeekFull"]["data"]["reason"] == "weekfull", firestore_swap_transactions
        assert firestore_swap_transactions["addWeekFullWrites"] == 0, firestore_swap_transactions
        assert firestore_swap_transactions["transferDayFull"]["data"]["reason"] == "dayfull", firestore_swap_transactions
        assert firestore_swap_transactions["transferDayFullWrites"] == 0, firestore_swap_transactions
        assert firestore_swap_transactions["exchangeDayFull"]["data"]["reason"] == "dayfull", firestore_swap_transactions
        assert firestore_swap_transactions["exchangeDayFullWrites"] == 0, firestore_swap_transactions

        cross_day = await page.evaluate("""() => {
            const sh = { id: 23, name: '23:00-00:00', start: '23:00', end: '00:00', tolerance: 5, cross: true };
            const sd = '2026-08-01';
            const punches = [
                { sid: '23', t: 's', date: '2026-08-01', time: '23:00', sd: sd },
                { sid: '23', t: 'e', date: '2026-08-02', time: '00:02', sd: '2026-08-02' }
            ];
            const status = ss(sh, punches, sd, sd);
            const adjacent = { sid: '23', t: 'e', date: '2026-08-03', time: '00:02', sd: '2026-08-02' };
            return {
                startMatched: !!status.sp,
                endMatched: !!status.ep,
                overall: status.ov,
                adjacentMatched: isPunchOfInstance(adjacent, sh, sd)
            };
        }""")
        assert cross_day == {
            "startMatched": True,
            "endMatched": True,
            "overall": "ok",
            "adjacentMatched": False,
        }, cross_day

        import_id_stability = await page.evaluate("""async () => {
            const oldTeam = TEAM, oldShifts = state.shifts, oldPicks = picks, oldReady = fbReady;
            try {
                fbReady = false;
                TEAM = [
                    { id: 13, name: '8597644', dept: '监控', shiftIds: [] },
                    { id: 17, name: '保留成员', dept: '监控', shiftIds: [8] }
                ];
                state.shifts = [
                    { id: 7, name: '旧名称', start: '07:00', end: '08:00', tolerance: 5, enabled: true, cross: false },
                    { id: 25, name: '01:00-02:00', start: '01:00', end: '02:00', tolerance: 5, enabled: true, cross: false }
                ];
                picks = {};
                const stable = stabilizeImportedShifts([
                    { id: 1, name: '新名称', start: '07:00', end: '08:00', tolerance: 8, enabled: true, cross: false },
                    { id: 2, name: '02:00-03:00', start: '02:00', end: '03:00', tolerance: 5, enabled: true, cross: false }
                ]);
                const allocate = createMemberIdAllocator();
                const firstNewId = allocate(), secondNewId = allocate();

                const now = new Date();
                const header = `${now.getMonth() + 1}月${now.getDate()}日`;
                const ws = XLSX.utils.aoa_to_sheet([
                    ['', header],
                    ['07:00~08:00', 8597644]
                ]);
                await parseDingTalkSchedule({ SheetNames: [`${header}新`], Sheets: { [`${header}新`]: ws } });
                return {
                    stableIds: stable.map(s => s.id),
                    firstNewId, secondNewId,
                    existingId: TEAM.find(m => m.name === '8597644')?.id,
                    retainedId: TEAM.find(m => m.name === '保留成员')?.id,
                    importedPicks: memberShifts(TEAM.find(m => m.name === '8597644'), tdStr()),
                    clearedPicks: memberShifts(TEAM.find(m => m.name === '保留成员'), tdStr())
                };
            } finally {
                TEAM = oldTeam;
                state.shifts = oldShifts;
                picks = oldPicks;
                fbReady = oldReady;
            }
        }""")
        assert import_id_stability["stableIds"][0] == 7, import_id_stability
        assert import_id_stability["stableIds"][1] > 1_000_000_000_000, import_id_stability
        assert import_id_stability["firstNewId"] > 1_000_000_000_000, import_id_stability
        assert import_id_stability["secondNewId"] == import_id_stability["firstNewId"] + 1, import_id_stability
        assert import_id_stability["existingId"] == 13, import_id_stability
        assert import_id_stability["retainedId"] == 17, import_id_stability
        assert import_id_stability["importedPicks"] == [7], import_id_stability
        assert import_id_stability["clearedPicks"] == [], import_id_stability

        device_unbind = await page.evaluate("""async () => {
            const old = { TEAM, claims, forceout, fbReady, supa, locCfg };
            const oldBinding = localStorage.getItem('cb6');
            const calls = [];
            try {
                TEAM = [
                    { id: 1, name: '管理员设备', dept: '管理' },
                    { id: 13, name: '8597644', dept: '监控' }
                ];
                claims = { '14': { id: '14', by_name: '8597644', expires_at: Date.now() + 60000 } };
                forceout = {};
                locCfg = { on: false, members: {} };
                fbReady = true;
                localStorage.setItem('cb6', '1');
                supa = {
                    from: table => {
                        if (table === 'claims') return {
                            select: async () => ({ data: [{ id: '14', by_name: '8597644' }], error: null })
                        };
                        throw new Error(`unexpected table ${table}`);
                    },
                    rpc: async (name, params) => {
                        calls.push([name, params]);
                        return {
                            data: {
                                '13': { ts: Date.now(), reason: params.p_reason },
                                '14': { ts: Date.now(), reason: params.p_reason }
                            },
                            error: null
                        };
                    }
                };
                const matched = claimForMember(TEAM[1]);
                renderMembers();
                const buttonCount = [...document.querySelectorAll('#membersList button')]
                    .filter(btn => btn.textContent.includes('设备解绑')).length;
                await unclaimAccount(13, '回归测试');
                return {
                    matchedId: matched?.id,
                    buttonCount,
                    bindingAfter: localStorage.getItem('cb6'),
                    calls,
                    remainingClaim: claims['14'] || null,
                    forcedCurrent: !!forceout['13'],
                    forcedHistorical: !!forceout['14']
                };
            } finally {
                TEAM = old.TEAM;
                claims = old.claims;
                forceout = old.forceout;
                fbReady = old.fbReady;
                supa = old.supa;
                locCfg = old.locCfg;
                if (oldBinding === null) localStorage.removeItem('cb6');
                else localStorage.setItem('cb6', oldBinding);
                renderAll();
            }
        }""")
        assert device_unbind["matchedId"] == "14", device_unbind
        assert device_unbind["buttonCount"] == 2, device_unbind
        assert device_unbind["bindingAfter"] == "1", device_unbind
        assert device_unbind["calls"] == [["claims_unbind_atomic", {
            "p_target_ids": ["14"],
            "p_force_ids": ["13", "14"],
            "p_reason": "回归测试",
        }]], device_unbind
        assert device_unbind["remainingClaim"] is None, device_unbind
        assert device_unbind["forcedCurrent"] is True, device_unbind
        assert device_unbind["forcedHistorical"] is True, device_unbind

        current_device_unbind = await page.evaluate("""async () => {
            const old = { TEAM, claims, forceout, fbReady, supa, selectedMember, pendingPwdMid, renderEmp, stopReminderTimer };
            const oldBinding = localStorage.getItem('cb6');
            const oldAuth = localStorage.getItem('cb6auth');
            try {
                TEAM = [{ id: 13, name: '8597644' }];
                claims = { '13': { id: '13', by_name: '8597644' } };
                forceout = {};
                fbReady = true;
                selectedMember = TEAM[0];
                pendingPwdMid = 13;
                localStorage.setItem('cb6', '13');
                localStorage.setItem('cb6auth', '1');
                renderEmp = () => {};
                stopReminderTimer = () => {};
                supa = {
                    from: () => ({ select: async () => ({ data: [{ id: '13', by_name: '8597644' }], error: null }) }),
                    rpc: async () => ({ data: { '13': { ts: Date.now(), reason: '当前设备解绑' } }, error: null })
                };
                const result = await unclaimAccount(13, '当前设备解绑');
                return {
                    result,
                    selected: selectedMember,
                    pending: pendingPwdMid,
                    binding: localStorage.getItem('cb6'),
                    auth: localStorage.getItem('cb6auth')
                };
            } finally {
                TEAM = old.TEAM;claims = old.claims;forceout = old.forceout;fbReady = old.fbReady;supa = old.supa;
                selectedMember = old.selectedMember;pendingPwdMid = old.pendingPwdMid;
                renderEmp = old.renderEmp;stopReminderTimer = old.stopReminderTimer;
                if (oldBinding === null) localStorage.removeItem('cb6');
                else localStorage.setItem('cb6', oldBinding);
                if (oldAuth === null) localStorage.removeItem('cb6auth');
                else localStorage.setItem('cb6auth', oldAuth);
            }
        }""")
        assert current_device_unbind == {
            "result": True,
            "selected": None,
            "pending": None,
            "binding": None,
            "auth": None,
        }, current_device_unbind

        independent_forceout_pull = await page.evaluate("""async () => {
            const old = { supa, fbReady, forceout, selectedMember, renderEmp, showToast, stopReminderTimer };
            const oldBinding = localStorage.getItem('cb6');
            const oldAuth = localStorage.getItem('cb6auth');
            const oldAuthTs = localStorage.getItem('cb6authTs');
            try {
                fbReady = true;
                forceout = {};
                selectedMember = { id: 13, name: '8597644' };
                localStorage.setItem('cb6', '13');
                localStorage.setItem('cb6auth', '1');
                localStorage.setItem('cb6authTs', '1');
                renderEmp = () => {};
                showToast = () => {};
                stopReminderTimer = () => {};
                supa = {
                    from: () => ({
                        select: () => ({
                            eq: () => ({
                                maybeSingle: async () => ({
                                    data: { id: 'forceout', data: { '13': { ts: Date.now(), reason: '实时强退' } } },
                                    error: null
                                })
                            })
                        })
                    })
                };
                const pulled = await syncForceOut();
                checkForceOut();
                return {
                    pulled,
                    selected: selectedMember,
                    binding: localStorage.getItem('cb6'),
                    auth: localStorage.getItem('cb6auth')
                };
            } finally {
                supa = old.supa;fbReady = old.fbReady;forceout = old.forceout;selectedMember = old.selectedMember;
                renderEmp = old.renderEmp;showToast = old.showToast;stopReminderTimer = old.stopReminderTimer;
                if (oldBinding === null) localStorage.removeItem('cb6');
                else localStorage.setItem('cb6', oldBinding);
                if (oldAuth === null) localStorage.removeItem('cb6auth');
                else localStorage.setItem('cb6auth', oldAuth);
                if (oldAuthTs === null) localStorage.removeItem('cb6authTs');
                else localStorage.setItem('cb6authTs', oldAuthTs);
            }
        }""")
        assert independent_forceout_pull == {
            "pulled": True,
            "selected": None,
            "binding": None,
            "auth": None,
        }, independent_forceout_pull

        historical_claim_blocks_login = await page.evaluate("""async () => {
            const old = { TEAM, claims, fbReady, selectedMember };
            try {
                TEAM = [{ id: 13, name: '8597644', dept: '监控' }];
                claims = { '14': { id: '14', by_name: '8597644', fp: 'other-device', expires_at: Date.now() + 60000 } };
                fbReady = true;selectedMember = null;
                document.getElementById('memberSelect').innerHTML = '<option value="13">8597644</option>';
                document.getElementById('memberSelect').value = '13';
                document.getElementById('empContent').innerHTML = '';
                await selectMember('13');
                return {
                    selected: selectedMember,
                    selectValue: document.getElementById('memberSelect').value,
                    blocked: document.getElementById('empContent').textContent.includes('占用')
                };
            } finally {
                TEAM = old.TEAM;claims = old.claims;fbReady = old.fbReady;selectedMember = old.selectedMember;
                renderAll();
            }
        }""")
        assert historical_claim_blocks_login["selected"] is None, historical_claim_blocks_login
        assert historical_claim_blocks_login["selectValue"] == "", historical_claim_blocks_login
        assert historical_claim_blocks_login["blocked"] is True, historical_claim_blocks_login

        unclaim_failure = await page.evaluate("""async () => {
            const old = { TEAM, claims, forceout, fbReady, supa, selectedMember, renderEmp, showToast };
            const oldBinding = localStorage.getItem('cb6');
            const oldAuth = localStorage.getItem('cb6auth');
            try {
                TEAM = [{ id: 13, name: '8597644' }];
                selectedMember = TEAM[0];
                claims = { '14': { id: '14', by_name: '8597644', expires_at: Date.now() + 60000 } };
                forceout = {};fbReady = true;
                localStorage.setItem('cb6', '13');
                localStorage.setItem('cb6auth', '1');
                renderEmp = () => {};
                showToast = () => {};
                supa = {
                    from: table => table === 'claims' ? {
                        select: async () => ({ data: [
                            { id: '14', by_name: '8597644' },
                            { id: '15', by_name: '8597644' }
                        ], error: null })
                    } : {},
                    rpc: async () => ({ data: null, error: { message: 'transaction denied' } })
                };
                const result = await unclaimAccount(13, '失败测试');
                checkForceOut();
                return {
                    result,
                    selectedId: selectedMember?.id,
                    binding: localStorage.getItem('cb6'),
                    auth: localStorage.getItem('cb6auth'),
                    forceoutPublished: !!forceout['13'] || !!forceout['14']
                };
            } finally {
                TEAM = old.TEAM;claims = old.claims;forceout = old.forceout;fbReady = old.fbReady;supa = old.supa;
                selectedMember = old.selectedMember;renderEmp = old.renderEmp;showToast = old.showToast;
                if (oldBinding === null) localStorage.removeItem('cb6');
                else localStorage.setItem('cb6', oldBinding);
                if (oldAuth === null) localStorage.removeItem('cb6auth');
                else localStorage.setItem('cb6auth', oldAuth);
            }
        }""")
        assert unclaim_failure == {
            "result": False,
            "selectedId": 13,
            "binding": "13",
            "auth": "1",
            "forceoutPublished": False,
        }, unclaim_failure

        admin_unbind_failure = await page.evaluate("""async () => {
            const old = {
                selectedMember, unclaimAccount, prompt: window.prompt,
                showToast, logEvent, renderEmp, stopReminderTimer
            };
            const notices = [], logs = [];
            const oldAuth = localStorage.getItem('cb6auth');
            try {
                selectedMember = { id: 13, name: '8597644' };
                localStorage.setItem('cb6auth', '1');
                window.prompt = () => '网络失败';
                unclaimAccount = async () => false;
                showToast = message => notices.push(message);
                logEvent = (...args) => logs.push(args);
                renderEmp = () => {};
                stopReminderTimer = () => {};
                const result = await adminUnbind();
                return {
                    result,
                    selectedId: selectedMember?.id,
                    auth: localStorage.getItem('cb6auth'),
                    notices,
                    logs
                };
            } finally {
                selectedMember = old.selectedMember;
                unclaimAccount = old.unclaimAccount;
                window.prompt = old.prompt;
                showToast = old.showToast;
                logEvent = old.logEvent;
                renderEmp = old.renderEmp;
                stopReminderTimer = old.stopReminderTimer;
                if (oldAuth === null) localStorage.removeItem('cb6auth');
                else localStorage.setItem('cb6auth', oldAuth);
            }
        }""")
        assert admin_unbind_failure == {
            "result": False,
            "selectedId": 13,
            "auth": "1",
            "notices": ["设备解绑失败，请检查网络后重试"],
            "logs": [],
        }, admin_unbind_failure

        reset_all_failure = await page.evaluate("""async () => {
            const old = {
                TEAM, claims, forceout, fbReady, supa, selectedMember,
                confirm: window.confirm, prompt: window.prompt,
                showToast, logEvent, renderAll, renderEmp, stopReminderTimer
            };
            const notices = [], logs = [];
            const oldAuth = localStorage.getItem('cb6auth');
            const oldBinding = localStorage.getItem('cb6');
            try {
                TEAM = [{ id: 13, name: '8597644' }];
                claims = { '14': { id: '14', by_name: '8597644' } };
                forceout = {};
                fbReady = true;
                selectedMember = TEAM[0];
                localStorage.setItem('cb6', '13');
                localStorage.setItem('cb6auth', '1');
                window.confirm = () => true;
                window.prompt = () => '批量失败';
                showToast = message => notices.push(message);
                logEvent = (...args) => logs.push(args);
                renderAll = () => {};
                renderEmp = () => {};
                stopReminderTimer = () => {};
                supa = {
                    from: table => table === 'claims' ? {
                        select: async () => ({ data: [
                            { id: '14', by_name: '8597644' },
                            { id: '15', by_name: '另一历史绑定' }
                        ], error: null })
                    } : {},
                    rpc: async () => ({ data: null, error: { message: 'transaction denied' } })
                };
                const result = await resetAllBindings();
                checkForceOut();
                return {
                    result,
                    selectedId: selectedMember?.id,
                    binding: localStorage.getItem('cb6'),
                    auth: localStorage.getItem('cb6auth'),
                    notices,
                    logs,
                    claimStillPresent: !!claims['14'],
                    forceoutPublished: !!forceout['13'] || !!forceout['14']
                };
            } finally {
                TEAM = old.TEAM;
                claims = old.claims;
                forceout = old.forceout;
                fbReady = old.fbReady;
                supa = old.supa;
                selectedMember = old.selectedMember;
                window.confirm = old.confirm;
                window.prompt = old.prompt;
                showToast = old.showToast;
                logEvent = old.logEvent;
                renderAll = old.renderAll;
                renderEmp = old.renderEmp;
                stopReminderTimer = old.stopReminderTimer;
                if (oldAuth === null) localStorage.removeItem('cb6auth');
                else localStorage.setItem('cb6auth', oldAuth);
                if (oldBinding === null) localStorage.removeItem('cb6');
                else localStorage.setItem('cb6', oldBinding);
            }
        }""")
        assert reset_all_failure["result"] is False, reset_all_failure
        assert reset_all_failure["selectedId"] == 13, reset_all_failure
        assert reset_all_failure["binding"] == "13", reset_all_failure
        assert reset_all_failure["auth"] == "1", reset_all_failure
        assert reset_all_failure["logs"] == [], reset_all_failure
        assert reset_all_failure["claimStillPresent"] is True, reset_all_failure
        assert reset_all_failure["forceoutPublished"] is False, reset_all_failure
        assert any("重置未完全成功" in message for message in reset_all_failure["notices"]), reset_all_failure

        claim_failure_blocks_login = await page.evaluate("""async () => {
            const old = {
                TEAM, supa, fbReady, selectedMember, pendingPwdMid,
                claimAccount, showToast, renderEmp, startReminderTimer,
                fsTested: _fsConnectionTested, fsOk: _fsConnectionOk
            };
            const notices = [];
            const oldAuth = localStorage.getItem('cb6auth');
            const oldBinding = localStorage.getItem('cb6');
            try {
                TEAM = [{ id: 13, name: '8597644', pwd: DEFAULT_PWD_HASH }];
                fbReady = true;
                _fsConnectionTested = false;
                _fsConnectionOk = true;
                localStorage.removeItem('cb6');
                localStorage.removeItem('cb6auth');
                supa = {
                    from: () => ({
                        select: async () => ({ data: null, error: { message: 'claim read failed' } })
                    })
                };
                const claimResult = await claimAccount(13);
                _fsConnectionTested = true;
                _fsConnectionOk = false;
                const disconnectedResult = await claimAccount(13);

                selectedMember = null;
                pendingPwdMid = 13;
                document.getElementById('pwdInput').value = '123456';
                document.getElementById('memberSelect').innerHTML = '<option value="13">8597644</option>';
                document.getElementById('memberSelect').value = '13';
                document.getElementById('empContent').innerHTML = '';
                claimAccount = async () => { throw new Error('claim timeout'); };
                showToast = message => notices.push(message);
                renderEmp = () => {};
                startReminderTimer = () => {};
                await confirmPwd();
                return {
                    claimResult,
                    disconnectedResult,
                    selected: selectedMember,
                    auth: localStorage.getItem('cb6auth'),
                    binding: localStorage.getItem('cb6'),
                    selectValue: document.getElementById('memberSelect').value,
                    content: document.getElementById('empContent').textContent,
                    notices
                };
            } finally {
                TEAM = old.TEAM;
                supa = old.supa;
                fbReady = old.fbReady;
                selectedMember = old.selectedMember;
                pendingPwdMid = old.pendingPwdMid;
                claimAccount = old.claimAccount;
                showToast = old.showToast;
                renderEmp = old.renderEmp;
                startReminderTimer = old.startReminderTimer;
                _fsConnectionTested = old.fsTested;
                _fsConnectionOk = old.fsOk;
                if (oldAuth === null) localStorage.removeItem('cb6auth');
                else localStorage.setItem('cb6auth', oldAuth);
                if (oldBinding === null) localStorage.removeItem('cb6');
                else localStorage.setItem('cb6', oldBinding);
                renderAll();
            }
        }""")
        assert claim_failure_blocks_login["claimResult"]["ok"] is False, claim_failure_blocks_login
        assert claim_failure_blocks_login["claimResult"]["reason"] == "network", claim_failure_blocks_login
        assert claim_failure_blocks_login["disconnectedResult"]["ok"] is False, claim_failure_blocks_login
        assert claim_failure_blocks_login["disconnectedResult"]["reason"] == "network", claim_failure_blocks_login
        assert claim_failure_blocks_login["selected"] is None, claim_failure_blocks_login
        assert claim_failure_blocks_login["auth"] is None, claim_failure_blocks_login
        assert claim_failure_blocks_login["binding"] is None, claim_failure_blocks_login
        assert claim_failure_blocks_login["selectValue"] == "", claim_failure_blocks_login
        assert "未登录" in claim_failure_blocks_login["content"], claim_failure_blocks_login
        assert any("检查超时" in message for message in claim_failure_blocks_login["notices"]), claim_failure_blocks_login

        import_failure_propagation = await page.evaluate("""async () => {
            const old = { picks, picksLocalVer, fbReady, supa, pullPicksSelCfg };
            try {
                picks = {};
                picksLocalVer = 0;
                fbReady = true;
                supa = {
                    rpc: async () => ({ data: { '2026-09-04': { '13': [7] } }, error: null })
                };
                pullPicksSelCfg = async () => false;
                const importResult = await persistImportedDailyPicks(
                    '2026-09-04',
                    [{ id: 13, shiftIds: [7] }]
                );

                let upsertCalls = 0;
                supa = {
                    from: () => ({
                        upsert: async () => {
                            upsertCalls++;
                            return { error: { message: 'config write failed' } };
                        }
                    })
                };
                const configResult = await syncToFB();
                return { importResult, configResult, upsertCalls };
            } finally {
                picks = old.picks;
                picksLocalVer = old.picksLocalVer;
                fbReady = old.fbReady;
                supa = old.supa;
                pullPicksSelCfg = old.pullPicksSelCfg;
            }
        }""")
        assert import_failure_propagation == {
            "importResult": False,
            "configResult": False,
            "upsertCalls": 1,
        }, import_failure_propagation

        reconcile_false_propagation = await page.evaluate("""async () => {
            const oldPull = pullPicksSelCfg;
            let calls = 0;
            try {
                pullPicksSelCfg = async () => { calls++; return false; };
                const result = await reconcilePicks();
                return { result, calls };
            } finally {
                pullPicksSelCfg = oldPull;
            }
        }""")
        assert reconcile_false_propagation == {"result": False, "calls": 4}, reconcile_false_propagation

        atomic_unbind_transaction = await page.evaluate("""async () => {
            const operations = [];
            const provider = Object.create(_FSProvider.prototype);
            provider._fs = {
                collection: name => ({ doc: id => ({ name, id }) }),
                runTransaction: async fn => fn({
                    get: async ref => ref.name === 'config'
                        ? { exists: true, data: () => ({ data: { legacy: { ts: 1 } } }) }
                        : { exists: true, data: () => ({ id: ref.id }) },
                    delete: ref => operations.push(['delete', ref.name, ref.id]),
                    set: (ref, value, options) => operations.push(['set', ref.name, ref.id, value, options])
                })
            };
            const result = await provider.rpc('claims_unbind_atomic', {
                p_target_ids: ['14', '15'],
                p_force_ids: ['13', '14', '15'],
                p_reason: '原子解绑测试'
            });
            return { result, operations };
        }""")
        assert atomic_unbind_transaction["result"]["error"] is None, atomic_unbind_transaction
        assert atomic_unbind_transaction["operations"][0:2] == [
            ["delete", "claims", "14"],
            ["delete", "claims", "15"],
        ], atomic_unbind_transaction
        forceout_write = atomic_unbind_transaction["operations"][2]
        assert forceout_write[0:3] == ["set", "config", "forceout"], atomic_unbind_transaction
        assert set(forceout_write[3]["data"].keys()) == {"legacy", "13", "14", "15"}, atomic_unbind_transaction

        bulk_import_transaction = await page.evaluate("""async () => {
            const docs = { picks: { data: {
                '2026-09-04': { '99': [8] },
                '2026-09-03': { '13': [9] }
            } } };
            let writes = 0;
            const provider = Object.create(_FSProvider.prototype);
            provider._fs = {
                collection: () => ({ doc: id => ({ id }) }),
                runTransaction: async fn => fn({
                    get: async ref => ({ exists: true, data: () => JSON.parse(JSON.stringify(docs[ref.id])) }),
                    set: (ref, value) => { writes++; docs[ref.id] = { ...docs[ref.id], ...JSON.parse(JSON.stringify(value)) }; }
                })
            };
            const result = await provider.rpc('picks_import_day', {
                p_date: '2026-09-04',
                p_members: { '13': ['7', 7], '17': [] }
            });
            return { result, writes, picks: docs.picks.data };
        }""")
        assert bulk_import_transaction["result"]["error"] is None, bulk_import_transaction
        assert bulk_import_transaction["writes"] == 1, bulk_import_transaction
        assert bulk_import_transaction["picks"] == {
            "2026-09-04": {"99": [8], "13": [7], "17": []},
            "2026-09-03": {"13": [9]},
        }, bulk_import_transaction

        missing_snapshot_field = await page.evaluate("""async () => {
            const provider = Object.create(_FSProvider.prototype);
            provider._fs = {
                collection: () => ({
                    doc: () => ({
                        get: async () => ({ exists: true, data: () => ({ updated_at: Date.now() }) })
                    })
                })
            };
            return await provider.rpc('picks_snapshot', {});
        }""")
        assert missing_snapshot_field["data"] is None, missing_snapshot_field
        assert "missing data field" in missing_snapshot_field["error"]["message"], missing_snapshot_field

        missing_snapshot_document = await page.evaluate("""async () => {
            const provider = Object.create(_FSProvider.prototype);
            provider._fs = {
                collection: () => ({
                    doc: () => ({ get: async () => ({ exists: false }) })
                })
            };
            return await provider.rpc('picks_snapshot', {});
        }""")
        assert missing_snapshot_document["data"] is None, missing_snapshot_document
        assert "document missing" in missing_snapshot_document["error"]["message"], missing_snapshot_document

        invalid_snapshot_types = await page.evaluate("""async () => {
            const check = async value => {
                const provider = Object.create(_FSProvider.prototype);
                provider._fs = {
                    collection: () => ({
                        doc: () => ({
                            get: async () => ({ exists: true, data: () => ({ data: value }) })
                        })
                    })
                };
                return await provider.rpc('picks_snapshot', {});
            };
            return {
                nullValue: await check(null),
                scalarValue: await check('corrupt'),
                arrayValue: await check([]),
                emptyObject: await check({})
            };
        }""")
        for key in ("nullValue", "scalarValue", "arrayValue"):
            assert invalid_snapshot_types[key]["data"] is None, invalid_snapshot_types
            assert "missing data field" in invalid_snapshot_types[key]["error"]["message"], invalid_snapshot_types
        assert invalid_snapshot_types["emptyObject"]["error"] is None, invalid_snapshot_types
        assert invalid_snapshot_types["emptyObject"]["data"]["data"] == {}, invalid_snapshot_types

        firestore_realtime_dispatch = await page.evaluate("""async () => {
            let snapshotHandler = null;
            const payloads = [];
            const provider = Object.create(_FSProvider.prototype);
            provider._listeners = [];
            provider._fs = {
                collection: table => ({
                    onSnapshot: handler => {
                        snapshotHandler = handler;
                        return () => {};
                    }
                })
            };
            provider.channel('config-sync')
                .on('postgres_changes', { event: '*', schema: 'public', table: 'config' }, payload => payloads.push(payload))
                .subscribe();
            snapshotHandler({ docChanges: () => [{
                type: 'added',
                doc: { id: 'initial', data: () => ({ data: {} }) }
            }] });
            snapshotHandler({ docChanges: () => [{
                type: 'modified',
                doc: { id: 'forceout', data: () => ({ data: { '13': { ts: 123 } } }) }
            }] });
            return { payloads, listenerCount: provider._listeners.length };
        }""")
        assert firestore_realtime_dispatch["listenerCount"] == 1, firestore_realtime_dispatch
        assert firestore_realtime_dispatch["payloads"] == [{
            "eventType": "UPDATE",
            "new": {"data": {"13": {"ts": 123}}, "id": "forceout"},
            "old": None,
        }], firestore_realtime_dispatch

        source = (ROOT / "index.html").read_text(encoding="utf-8")
        assert "picks[date][fromId]" not in source
        assert "picks[s.date][s.fromId]" not in source
        assert "picks[ds][editingId]" not in source
        assert "newTeam.forEach((m,i)=>m.id=i+1)" not in source

        await browser.close()
        relevant_errors = [e for e in errors if "favicon" not in e.lower()]
        assert not relevant_errors, f"页面运行期错误: {relevant_errors}"
        print("PASS: ID 归一化、导入事务、设备解绑、月度统计、成员 14 可见性、跨日打卡实例匹配")


if __name__ == "__main__":
    asyncio.run(main())
