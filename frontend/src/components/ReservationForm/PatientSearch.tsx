import { useState, useEffect, useRef } from 'react';
import { Search, Plus, X as XIcon } from 'lucide-react';
import type { Patient, CandidateResponse } from '../../types';
import { searchPatients, createPatient, findCandidates } from '../../api/client';
import { extractErrorMessage } from '../../utils/errorUtils';

interface PatientSearchProps {
  onSelect: (patient: Patient) => void;
  onClear: () => void;
  selectedName: string;
}

export default function PatientSearch({ onSelect, onClear, selectedName }: PatientSearchProps) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Patient[]>([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [showNewForm, setShowNewForm] = useState(false);
  const [newMode, setNewMode] = useState<'split' | 'full_name'>('split');
  const [newLastName, setNewLastName] = useState('');
  const [newFirstName, setNewFirstName] = useState('');
  const [newFullName, setNewFullName] = useState('');
  const [newReading, setNewReading] = useState('');
  const [newPhone, setNewPhone] = useState('');
  const [candidates, setCandidates] = useState<CandidateResponse[]>([]);
  const [showCandidates, setShowCandidates] = useState(false);
  const [confirmNew, setConfirmNew] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const lastNameRef = useRef<HTMLInputElement>(null);
  const firstNameRef = useRef<HTMLInputElement>(null);
  const fullNameRef = useRef<HTMLInputElement>(null);
  const readingRef = useRef<HTMLInputElement>(null);
  const phoneRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (query.length >= 2) {
      const timer = setTimeout(async () => {
        try {
          const res = await searchPatients(query);
          setResults(res.data ?? []);
          setShowDropdown(true);
        } catch (err) {
          setResults([]);
          setError(extractErrorMessage(err, '患者検索に失敗しました'));
        }
      }, 300);
      return () => clearTimeout(timer);
    } else {
      setResults([]);
      setShowDropdown(false);
    }
  }, [query]);

  // 候補検索
  useEffect(() => {
    const hasName = newMode === 'split' ? (newLastName && newFirstName) : newFullName;
    if (!hasName) {
      setCandidates([]);
      setShowCandidates(false);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const res = await findCandidates({
          registration_mode: newMode,
          last_name: newMode === 'split' ? newLastName : undefined,
          first_name: newMode === 'split' ? newFirstName : undefined,
          full_name: newMode === 'full_name' ? newFullName : undefined,
          reading: newReading || undefined,
          phone: newPhone || undefined,
        });
        const data = res.data ?? [];
        setCandidates(data);
        setShowCandidates(data.length > 0);
        setConfirmNew(false);
      } catch {
        setCandidates([]);
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [newMode, newLastName, newFirstName, newFullName, newReading, newPhone]);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    if (showNewForm) {
      if (newMode === 'full_name') fullNameRef.current?.focus();
      else lastNameRef.current?.focus();
    }
  }, [showNewForm, newMode]);

  const handleEnterNext = (e: React.KeyboardEvent, nextRef: React.RefObject<HTMLInputElement | null>) => {
    if (e.key === 'Enter') { e.preventDefault(); nextRef.current?.focus(); }
  };

  const handleCreatePatient = async () => {
    const isSplit = newMode === 'split';
    const hasName = isSplit ? (newLastName && newFirstName) : newFullName;
    if (!hasName) return;
    if (candidates.length > 0 && !confirmNew) {
      setShowCandidates(true);
      setError('既存患者候補があります。確認してください。');
      return;
    }
    const displayName = isSplit ? `${newLastName} ${newFirstName}` : newFullName;
    if (!window.confirm(`「${displayName}」を新規登録しますか？`)) return;
    setError(null);
    try {
      const data: Record<string, unknown> = {
        registration_mode: newMode,
        reading: newReading || undefined,
        phone: newPhone || undefined,
      };
      if (isSplit) {
        data.last_name = newLastName;
        data.first_name = newFirstName;
      } else {
        data.full_name = newFullName;
      }
      const res = await createPatient(data as Partial<Patient>);
      onSelect(res.data);
      resetNewForm();
    } catch (err) {
      setError(extractErrorMessage(err, '患者の登録に失敗しました'));
    }
  };

  const resetNewForm = () => {
    setShowNewForm(false);
    setNewMode('split');
    setNewLastName(''); setNewFirstName('');
    setNewFullName(''); setNewReading('');
    setNewPhone('');
    setCandidates([]); setShowCandidates(false); setConfirmNew(false);
    setQuery('');
  };

  return (
    <div ref={wrapperRef} className="relative">
      {error && (
        <div className="mb-2 p-2 bg-red-50 border border-red-200 rounded text-red-700 text-xs">{error}</div>
      )}
      <div className="relative">
        {selectedName ? (
          <div className="flex items-center w-full border rounded px-3 py-2 text-sm bg-blue-50 border-blue-200">
            <Search size={16} className="text-blue-400 mr-2 shrink-0" />
            <span className="font-medium text-blue-800 truncate flex-1">{selectedName}</span>
            <button
              type="button"
              onClick={() => { onClear(); setQuery(''); }}
              className="ml-2 p-0.5 rounded hover:bg-blue-100 text-blue-400 hover:text-blue-600 shrink-0"
              title="患者選択を解除"
            >
              <XIcon size={16} />
            </button>
          </div>
        ) : (
          <>
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="名前・カナ・電話番号で検索"
              className="w-full border rounded pl-9 pr-3 py-2 text-sm"
            />
          </>
        )}
      </div>

      {showDropdown && results.length > 0 && (
        <div className="absolute z-20 w-full mt-1 bg-white border rounded shadow-lg max-h-48 overflow-auto">
          {results.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => { onSelect(p); setQuery(''); setShowDropdown(false); }}
              className="w-full text-left px-3 py-2 text-sm hover:bg-blue-50 border-b last:border-b-0"
            >
              <span className="font-medium">{p.name}</span>
              {p.patient_number && <span className="text-gray-500 ml-2">#{p.patient_number}</span>}
              {p.reading && <span className="text-gray-400 ml-2">{p.reading}</span>}
              {!p.reading && p.last_name_kana && <span className="text-gray-400 ml-2">{p.last_name_kana} {p.first_name_kana}</span>}
              {p.phone && <span className="text-gray-500 ml-2">{p.phone}</span>}
            </button>
          ))}
        </div>
      )}

      {showDropdown && query.length >= 2 && results.length === 0 && (
        <div className="absolute z-20 w-full mt-1 bg-white border rounded shadow-lg p-3 text-sm text-gray-500">
          該当する患者がいません
        </div>
      )}

      <button
        type="button"
        onClick={() => setShowNewForm(!showNewForm)}
        className="mt-1 flex items-center gap-1 text-sm text-blue-500 hover:text-blue-700"
      >
        <Plus size={14} /> 新規患者登録
      </button>

      {showNewForm && (
        <div className="mt-2 p-3 bg-gray-50 rounded border space-y-2">
          <label className="flex items-center gap-2 text-xs">
            <input type="checkbox" checked={newMode === 'full_name'}
              onChange={(e) => setNewMode(e.target.checked ? 'full_name' : 'split')} />
            フルネームで登録
          </label>
          <div className="grid grid-cols-2 gap-2">
            {newMode === 'split' ? (
              <>
                <input ref={lastNameRef} type="text" value={newLastName} onChange={(e) => setNewLastName(e.target.value)}
                  onKeyDown={(e) => handleEnterNext(e, firstNameRef)}
                  placeholder="姓（必須）" className="w-full border rounded px-3 py-1.5 text-sm" />
                <input ref={firstNameRef} type="text" value={newFirstName} onChange={(e) => setNewFirstName(e.target.value)}
                  onKeyDown={(e) => handleEnterNext(e, readingRef)}
                  placeholder="名（必須）" className="w-full border rounded px-3 py-1.5 text-sm" />
              </>
            ) : (
              <input ref={fullNameRef} type="text" value={newFullName} onChange={(e) => setNewFullName(e.target.value)}
                onKeyDown={(e) => handleEnterNext(e, readingRef)}
                placeholder="フルネーム（必須）" className="col-span-2 w-full border rounded px-3 py-1.5 text-sm" />
            )}
          </div>
          <input ref={readingRef} type="text" value={newReading} onChange={(e) => setNewReading(e.target.value)}
            onKeyDown={(e) => handleEnterNext(e, phoneRef)}
            placeholder="読み方（カタカナ / ローマ字）" className="w-full border rounded px-3 py-1.5 text-sm" />
          <input ref={phoneRef} type="text" value={newPhone} onChange={(e) => setNewPhone(e.target.value)}
            placeholder="電話番号" className="w-full border rounded px-3 py-1.5 text-sm" />

          {/* 候補表示 */}
          {showCandidates && candidates.length > 0 && (
            <div className="p-2 bg-red-50 border-2 border-red-400 rounded space-y-1 text-xs shadow-md">
              <p className="font-bold text-red-700">⚠ 同姓同名の既存患者がいます！</p>
              {candidates.map((c) => (
                <div key={c.patient.id} className="flex items-center justify-between p-1.5 bg-white rounded border">
                  <div>
                    <span className="font-medium">{c.patient.name}</span>
                    <span className="text-gray-500 ml-1">#{c.patient.patient_number}</span>
                    {c.patient.phone && <span className="text-gray-500 ml-1">{c.patient.phone}</span>}
                    <span className="ml-1 text-yellow-700">({c.match_reasons.join(', ')})</span>
                  </div>
                  <button type="button" onClick={() => { onSelect(c.patient); resetNewForm(); }}
                    className="px-2 py-0.5 bg-blue-500 text-white rounded hover:bg-blue-600 whitespace-nowrap">
                    この患者を使う
                  </button>
                </div>
              ))}
              <button type="button" onClick={() => { setConfirmNew(true); setShowCandidates(false); }}
                className="text-gray-600 underline hover:text-gray-800">
                それでも新規登録する
              </button>
            </div>
          )}

          <button
            type="button"
            onClick={handleCreatePatient}
            disabled={newMode === 'split' ? (!newLastName || !newFirstName) : !newFullName}
            className="px-3 py-1.5 text-sm bg-green-500 text-white rounded hover:bg-green-600 disabled:opacity-50"
          >
            {confirmNew ? '新規登録する' : '登録'}
          </button>
        </div>
      )}
    </div>
  );
}
