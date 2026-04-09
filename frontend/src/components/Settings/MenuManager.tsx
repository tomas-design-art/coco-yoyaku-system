import { useState, useEffect } from 'react';
import { Plus, Edit2, Trash2 } from 'lucide-react';
import type { Menu, ReservationColor } from '../../types';
import { getMenus, createMenu, updateMenu, deleteMenu, purgeMenu, getReservationColors } from '../../api/client';
import { extractErrorMessage } from '../../utils/errorUtils';

export default function MenuManager() {
  const [menus, setMenus] = useState<Menu[]>([]);
  const [colors, setColors] = useState<ReservationColor[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [name, setName] = useState('');
  const [durationMinutes, setDurationMinutes] = useState(30);
  const [isDurationVariable, setIsDurationVariable] = useState(false);
  const [maxDurationMinutes, setMaxDurationMinutes] = useState<number | ''>('');
  const [price, setPrice] = useState<number | ''>('');
  const [selectedColorId, setSelectedColorId] = useState<number | null>(null);
  const [editingWasInactive, setEditingWasInactive] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    try {
      const [menuRes, colorRes] = await Promise.all([getMenus(), getReservationColors()]);
      setMenus(menuRes.data ?? []);
      setColors(colorRes.data ?? []);
    } catch {
      setMenus([]);
      setColors([]);
    }
  };

  useEffect(() => { fetchData(); }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const data = {
      name,
      duration_minutes: durationMinutes,
      is_duration_variable: isDurationVariable,
      max_duration_minutes: isDurationVariable ? (maxDurationMinutes || durationMinutes) : undefined,
      price: price || undefined,
      color_id: selectedColorId,
    };
    try {
      if (editingId) {
        await updateMenu(editingId, { ...data, is_active: editingWasInactive ? true : undefined });
      } else {
        await createMenu({ ...data, display_order: menus.length });
      }
      resetForm();
      fetchData();
    } catch (err) {
      setError(extractErrorMessage(err, 'メニューの保存に失敗しました'));
    }
  };

  const resetForm = () => {
    setName('');
    setDurationMinutes(30);
    setIsDurationVariable(false);
    setMaxDurationMinutes('');
    setPrice('');
    setSelectedColorId(null);
    setEditingId(null);
    setEditingWasInactive(false);
    setShowForm(false);
  };

  const handleEdit = (m: Menu) => {
    setEditingId(m.id);
    setName(m.name);
    setDurationMinutes(m.duration_minutes);
    setIsDurationVariable(!!m.is_duration_variable);
    setMaxDurationMinutes(m.max_duration_minutes || '');
    setPrice(m.price || '');
    setSelectedColorId(m.color_id);
    setEditingWasInactive(!m.is_active);
    setShowForm(true);
  };

  const handleDelete = async (id: number) => {
    if (confirm('このメニューを無効化しますか？')) {
      try {
        await deleteMenu(id);
        fetchData();
      } catch (err) {
        setError(extractErrorMessage(err, 'メニューの無効化に失敗しました'));
      }
    }
  };

  const handlePermanentDelete = async (id: number) => {
    const confirmed = window.confirm('本当に削除しますか？\n削除されたデータは復元できません。');
    if (!confirmed) return;
    try {
      await purgeMenu(id);
      fetchData();
    } catch (err) {
      setError(extractErrorMessage(err, 'メニューの完全削除に失敗しました'));
    }
  };

  return (
    <div className="max-w-2xl mx-auto p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">メニュー管理</h1>
        <button onClick={() => { setShowForm(true); setEditingId(null); }} className="flex items-center gap-1 px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600">
          <Plus size={16} /> 追加
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{error}</div>
      )}

      {showForm && (
        <form onSubmit={handleSubmit} className="mb-6 p-4 bg-gray-50 rounded-lg border space-y-3">
          <div>
            <label className="block text-sm font-medium mb-1">メニュー名 <span className="text-red-500">*</span></label>
            <input value={name} onChange={(e) => setName(e.target.value)} className="w-full border rounded px-3 py-2" required />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium mb-1">施術時間（分） <span className="text-red-500">*</span></label>
              <input type="number" value={durationMinutes} onChange={(e) => setDurationMinutes(Number(e.target.value))}
                min={5} step={5} className="w-full border rounded px-3 py-2" required />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">料金（円）</label>
              <input type="number" value={price} onChange={(e) => setPrice(e.target.value ? Number(e.target.value) : '')}
                min={0} className="w-full border rounded px-3 py-2" />
            </div>
          </div>
          <div className="space-y-2">
            <label className="inline-flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={isDurationVariable}
                onChange={(e) => setIsDurationVariable(e.target.checked)}
              />
              可変時間メニュー（10分刻み）
            </label>
            {isDurationVariable && (
              <div>
                <label className="block text-sm font-medium mb-1">最大時間（分）</label>
                <input
                  type="number"
                  value={maxDurationMinutes}
                  onChange={(e) => setMaxDurationMinutes(e.target.value ? Number(e.target.value) : '')}
                  min={durationMinutes}
                  step={10}
                  className="w-full border rounded px-3 py-2"
                  required
                />
              </div>
            )}
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">分類タグ（予約色）</label>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => setSelectedColorId(null)}
                className={`px-3 py-1 rounded-full text-xs border-2 transition-colors ${selectedColorId === null ? 'border-gray-700 shadow bg-gray-100' : 'border-transparent hover:border-gray-300 bg-gray-50 text-gray-500'}`}>
                なし
              </button>
              {colors.map((c) => (
                <button key={c.id} type="button" onClick={() => setSelectedColorId(c.id)}
                  className={`flex items-center gap-1 px-3 py-1 rounded-full text-xs border-2 transition-colors ${selectedColorId === c.id ? 'border-gray-700 shadow' : 'border-transparent hover:border-gray-300'}`}
                  style={{ backgroundColor: c.color_code + '22', color: c.color_code }}>
                  <span className="inline-block w-3 h-3 rounded-full" style={{ backgroundColor: c.color_code }} />
                  {c.name}
                </button>
              ))}
            </div>
          </div>
          <div className="flex gap-2">
            <button type="submit" className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600">
              {editingId ? (editingWasInactive ? '更新して再有効化' : '更新') : '追加'}
            </button>
            <button type="button" onClick={resetForm} className="px-4 py-2 border rounded hover:bg-gray-100">キャンセル</button>
          </div>
        </form>
      )}

      <div className="space-y-2">
        {menus.length === 0 && (
          <p className="text-center text-gray-400 text-sm py-8">メニューが登録されていません</p>
        )}
        {menus.map((m) => (
          <div key={m.id} className={`flex items-center justify-between p-3 bg-white rounded border ${!m.is_active ? 'opacity-50' : ''}`}>
            <div className="flex items-center gap-2">
              {m.color && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs" style={{ backgroundColor: m.color.color_code + '22', color: m.color.color_code }}>
                  <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ backgroundColor: m.color.color_code }} />
                  {m.color.name}
                </span>
              )}
              <span className="font-medium">{m.name}</span>
              <span className="text-sm text-gray-500">{m.duration_minutes}分</span>
              {m.is_duration_variable && (
                <span className="text-xs text-cyan-700 bg-cyan-50 px-2 py-0.5 rounded">
                  可変 {m.duration_minutes}-{m.max_duration_minutes || m.duration_minutes}分
                </span>
              )}
              {m.price != null && m.price > 0 && <span className="text-sm text-gray-500">¥{m.price.toLocaleString()}</span>}
              {!m.is_active && <span className="text-xs bg-gray-200 px-2 py-0.5 rounded">無効</span>}
            </div>
            <div className="flex gap-1">
              <button onClick={() => handleEdit(m)} className="p-1.5 hover:bg-gray-100 rounded"><Edit2 size={14} /></button>
              {m.is_active && (
                <button onClick={() => handleDelete(m.id)} className="p-1.5 hover:bg-red-50 text-red-500 rounded"><Trash2 size={14} /></button>
              )}
              {!m.is_active && (
                <button onClick={() => handlePermanentDelete(m.id)} className="p-1.5 hover:bg-red-50 text-red-600 rounded" title="完全削除"><Trash2 size={14} /></button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
