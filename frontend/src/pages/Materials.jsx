import { useState, useEffect, useCallback } from 'react'
import { Plus, Pencil, Trash2, X, Check, Star } from 'lucide-react'
import { getMaterialsAll, createMaterial, updateMaterial, deleteMaterial, permanentDeleteMaterial, setDefaultMaterial } from '../lib/api'
import Modal from '../components/Modal'
import { formatPrice, ERROR_STYLE, getInputStyle } from '../lib/constants'
import { validateField } from '../lib/validation'

function validateMaterialField(name, value) {
  return validateField('material', name, value)
}

const colorMap = {
  black: '#1a1a1a', Black: '#1a1a1a', white: '#ffffff', White: '#ffffff',
  red: '#ef4444', Red: '#ef4444', orange: '#f97316', gray: '#9ca3af',
  'olive green': '#6b8e23', 'pine green': '#01796f', 'gold black': '#b8860b',
  'gold blue coper': '#d4a574', 'gold silver red': '#c0a080', walnut: '#5c4033',
  'dark mahaguni': '#4a0e0e', blue: '#3b82f6', 'lavander purple': '#b39ddb',
  transparent: '#e0e0e0', TRANSPARENT: '#e0e0e0',
}

function StatusBadge({ active }) {
  return (
    <span
      className="inline-flex px-2.5 py-0.5 rounded-full text-[11px] font-semibold"
      style={{
        backgroundColor: active ? 'rgba(34, 197, 94, 0.18)' : 'rgba(239, 68, 68, 0.15)',
        color: active ? '#4ade80' : '#f87171',
      }}
    >
      {active ? 'فعال' : 'غیرفعال'}
    </span>
  )
}

function ColorDot({ color }) {
  return (
    <span
      className="w-3.5 h-3.5 rounded-full border shrink-0 inline-block"
      style={{
        background: colorMap[color?.toLowerCase()] || color || '#ccc',
        borderColor: 'var(--border-color)',
      }}
    />
  )
}

export default function Materials() {
  const [materials, setMaterials] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showModal, setShowModal] = useState(false)
  const [editItem, setEditItem] = useState(null)
  const [form, setForm] = useState({ name: '', price_per_kg: '', waste_pct: '0.05', color: '', notes: '' })
  const [errors, setErrors] = useState({})
  const [touched, setTouched] = useState({})
  const [submitError, setSubmitError] = useState(null)

  const loadMaterials = useCallback(async (signal) => {
    try {
      const res = await getMaterialsAll(signal ? { signal } : undefined)
      setMaterials(Array.isArray(res.data) ? res.data : [])
      setError(null)
    } catch (e) {
      if (e?.name !== 'CanceledError' && e?.code !== 'ERR_CANCELED') {
        console.error('Failed to load materials:', e)
        setError('خطا در بارگذاری مواد اولیه')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    loadMaterials(controller.signal)
    return () => controller.abort()
  }, [loadMaterials])

  function openAdd() {
    setEditItem(null)
    setForm({ name: '', price_per_kg: '', waste_pct: '0.05', color: '', notes: '' })
    setErrors({})
    setTouched({})
    setSubmitError(null)
    setShowModal(true)
  }

  function openEdit(m) {
    setEditItem(m)
    setForm({
      name: m.name,
      price_per_kg: m.price_per_kg,
      waste_pct: m.waste_pct,
      color: m.color,
      notes: m.notes || '',
    })
    setErrors({})
    setTouched({})
    setSubmitError(null)
    setShowModal(true)
  }

  function handleFieldChange(name, value) {
    setForm((prev) => ({ ...prev, [name]: value }))
    if (touched[name]) {
      setErrors((prev) => ({ ...prev, [name]: validateMaterialField(name, value) }))
    }
  }

  function handleFieldBlur(name, value) {
    setTouched((prev) => ({ ...prev, [name]: true }))
    setErrors((prev) => ({ ...prev, [name]: validateMaterialField(name, value) }))
  }

  async function handleSave() {
    const requiredFields = ['name', 'price_per_kg']
    const formErrors = {}
    const allTouched = {}
    for (const field of requiredFields) {
      allTouched[field] = true
      const err = validateMaterialField(field, form[field])
      if (err) formErrors[field] = err
    }
    setTouched(allTouched)
    setErrors(formErrors)
    setSubmitError(null)

    if (Object.keys(formErrors).length > 0) {
      setSubmitError('لطفاً فیلدهای الزامی را پر کنید')
      return
    }

    const data = {
      name: form.name,
      price_per_kg: parseFloat(form.price_per_kg),
      waste_pct: parseFloat(form.waste_pct),
      color: form.color,
      notes: form.notes,
    }
    try {
      if (editItem) {
        await updateMaterial(editItem.id, data)
      } else {
        await createMaterial(data)
      }
      setShowModal(false)
      loadMaterials()
    } catch (e) {
      console.error('Failed to save material:', e)
      const msg = e?.response?.data?.detail || e?.message || 'خطا در ذخیره‌سازی'
      setSubmitError(msg)
    }
  }

  async function handleSetDefault(m) {
    try {
      await setDefaultMaterial(m.id);
      loadData();
    } catch (e) {
      console.error('Failed to set default material:', e);
    }
  }

  async function handleDelete(m) {
    if (!confirm(`"${m.name} ${m.color || ''}" مخفی شود؟`)) return
    try {
      await deleteMaterial(m.id)
      loadMaterials()
    } catch (e) {
      alert('خطا: ' + (e.response?.data?.detail || e.message))
      console.error('Failed to delete material:', e)
    }
  }

  async function handlePermanentDelete(m) {
    if (!confirm(`"${m.name} ${m.color || ''}" برای همیشه حذف شود؟ این عملیات غیرقابل بازگشت است!`)) return
    if (!confirm('مطمئن هستید؟')) return
    try {
      await permanentDeleteMaterial(m.id)
      loadMaterials()
    } catch (e) {
      alert(e.response?.data?.detail || 'خطا: ' + e.message)
      console.error('Failed to permanently delete material:', e)
    }
  }

  async function toggleActive(m) {
    try {
      await updateMaterial(m.id, { is_active: !m.is_active })
      loadMaterials()
    } catch (e) {
      console.error('Failed to toggle active:', e)
    }
  }

  const inputStyle = (fieldName) => getInputStyle(fieldName, touched, errors)

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-sm" style={{ color: 'var(--text-muted)' }}>در حال بارگذاری...</div>
      </div>
    )
  }
  if (error) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-sm" style={{ color: '#ef4444' }}>{error}</div>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight" style={{ color: '#ffffff' }}>
            مواد اولیه
          </h1>
          <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
            {materials.length} ماده · قیمت/کیلو و ضایعات
          </p>
        </div>
        <button type="button" onClick={openAdd} className="btn-primary">
          <Plus size={16} />
          افزودن ماده
        </button>
      </div>

      {materials.length === 0 ? (
        <div className="card p-10 text-center text-sm" style={{ color: 'var(--text-muted)' }}>
          ماده‌ای ثبت نشده است
        </div>
      ) : (
        <>
          <div className="hidden sm:block card overflow-hidden">
            <table className="w-full text-sm" dir="rtl">
              <thead>
                <tr className="border-b" style={{ borderColor: 'var(--border-color)' }}>
                  <th className="px-4 py-3 text-right font-medium" style={{ color: 'var(--text-muted)' }}>نام</th>
                  <th className="px-4 py-3 text-right font-medium" style={{ color: 'var(--text-muted)' }}>رنگ</th>
                  <th className="px-4 py-3 text-right font-medium" style={{ color: 'var(--text-muted)' }}>قیمت/کیلو</th>
                  <th className="px-4 py-3 text-right font-medium" style={{ color: 'var(--text-muted)' }}>ضایعات</th>
                  <th className="px-4 py-3 text-right font-medium" style={{ color: 'var(--text-muted)' }}>وضعیت</th>
                  <th className="px-4 py-3 text-right font-medium" style={{ color: 'var(--text-muted)' }}>عملیات</th>
                </tr>
              </thead>
              <tbody>
                {materials.map((m) => (
                  <tr key={m.id} className="table-row">
                    <td className="px-4 py-3 font-medium" style={{ color: 'var(--text-primary)' }}>
                      <div className="flex items-center gap-2">
                        <span>{m.name}</span>
                        {m.is_default && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/20 text-amber-400 border border-amber-500/30">
                            <Star size={10} className="fill-amber-400" />
                            پیش‌فرض
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center gap-2" style={{ color: 'var(--text-secondary)' }}>
                        <ColorDot color={m.color} />
                        {m.color || '—'}
                      </span>
                    </td>
                    <td className="px-4 py-3" style={{ color: 'var(--text-primary)' }}>
                      {formatPrice(m.price_per_kg)}
                    </td>
                    <td className="px-4 py-3" style={{ color: 'var(--text-secondary)' }}>
                      %{((m.waste_pct || 0) * 100).toFixed(0)}
                    </td>
                    <td className="px-4 py-3">
                      <button type="button" onClick={() => toggleActive(m)} title="تغییر وضعیت">
                        <StatusBadge active={m.is_active} />
                      </button>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5">
                        <button
                          type="button"
                          onClick={() => handleSetDefault(m)}
                          className={`p-2 rounded-lg transition-colors ${
                            m.is_default ? 'text-amber-400 bg-amber-500/10' : 'text-slate-400 hover:text-amber-400 hover:bg-slate-800'
                          }`}
                          title={m.is_default ? 'فیلامنت پیش‌فرض است' : 'تنظیم به‌عنوان فیلامنت پیش‌فرض'}
                        >
                          <Star size={14} className={m.is_default ? 'fill-amber-400' : ''} />
                        </button>
                        <button
                          type="button"
                          onClick={() => openEdit(m)}
                          className="p-2 rounded-lg"
                          style={{ color: 'var(--accent)', backgroundColor: 'var(--accent-light)' }}
                          title="ویرایش"
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete(m)}
                          className="p-2 rounded-lg"
                          style={{ backgroundColor: 'rgba(239,68,68,0.12)', color: '#f87171' }}
                          title="حذف (غیرفعال)"
                        >
                          <Trash2 size={14} />
                        </button>
                        <button
                          type="button"
                          onClick={() => handlePermanentDelete(m)}
                          className="p-2 rounded-lg"
                          style={{ backgroundColor: 'rgba(220,38,38,0.12)', color: '#dc2626' }}
                          title="حذف دائمی"
                        >
                          <X size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="sm:hidden space-y-3">
            {materials.map((m) => (
              <div key={m.id} className="card p-4">
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <ColorDot color={m.color} />
                    <span className="font-medium text-sm truncate" style={{ color: 'var(--text-primary)' }}>
                      {m.name}
                    </span>
                  </div>
                  <button type="button" onClick={() => toggleActive(m)}>
                    <StatusBadge active={m.is_active} />
                  </button>
                </div>
                <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs mb-3" style={{ color: 'var(--text-secondary)' }}>
                  <span>{m.color || '—'}</span>
                  <span>{formatPrice(m.price_per_kg)}/کیلو</span>
                  <span>%{((m.waste_pct || 0) * 100).toFixed(0)} ضایعات</span>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => openEdit(m)}
                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs"
                    style={{ background: 'var(--accent-light)', color: 'var(--accent)' }}
                  >
                    <Pencil size={12} /> ویرایش
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDelete(m)}
                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs"
                    style={{ background: 'rgba(239,68,68,0.12)', color: '#f87171' }}
                  >
                    <Trash2 size={12} /> مخفی
                  </button>
                  <button
                    type="button"
                    onClick={() => handlePermanentDelete(m)}
                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs"
                    style={{ background: 'rgba(220,38,38,0.14)', color: '#dc2626' }}
                  >
                    <Trash2 size={12} /> حذف دائمی
                  </button>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      <Modal
        isOpen={showModal}
        onClose={() => setShowModal(false)}
        title={editItem ? 'ویرایش ماده' : 'افزودن ماده جدید'}
      >
        <div className="space-y-4">
          {submitError && (
            <div
              className="p-3 rounded-lg text-sm"
              style={{
                background: 'rgba(239,68,68,0.15)',
                color: '#ef4444',
                border: '1px solid rgba(239,68,68,0.3)',
              }}
            >
              {submitError}
            </div>
          )}
          <div>
            <label className="block text-sm mb-1" style={{ color: 'var(--text-secondary)' }}>
              نام ماده *
            </label>
            <input
              value={form.name}
              onChange={(e) => handleFieldChange('name', e.target.value)}
              onBlur={() => handleFieldBlur('name', form.name)}
              className="input-field w-full"
              style={inputStyle('name')}
            />
            {touched.name && errors.name && <span style={ERROR_STYLE}>{errors.name}</span>}
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm mb-1" style={{ color: 'var(--text-secondary)' }}>
                قیمت هر کیلو (تومان) *
              </label>
              <input
                type="number"
                value={form.price_per_kg}
                onChange={(e) => handleFieldChange('price_per_kg', e.target.value)}
                onBlur={() => handleFieldBlur('price_per_kg', form.price_per_kg)}
                className="input-field w-full"
                style={inputStyle('price_per_kg')}
              />
              {touched.price_per_kg && errors.price_per_kg && (
                <span style={ERROR_STYLE}>{errors.price_per_kg}</span>
              )}
            </div>
            <div>
              <label className="block text-sm mb-1" style={{ color: 'var(--text-secondary)' }}>
                ضریب ضایعات
              </label>
              <input
                type="number"
                step="0.01"
                value={form.waste_pct}
                onChange={(e) => handleFieldChange('waste_pct', e.target.value)}
                className="input-field w-full"
                style={inputStyle('waste_pct')}
              />
            </div>
          </div>
          <div>
            <label className="block text-sm mb-1" style={{ color: 'var(--text-secondary)' }}>
              رنگ
            </label>
            <input
              value={form.color}
              onChange={(e) => handleFieldChange('color', e.target.value)}
              className="input-field w-full"
              style={inputStyle('color')}
            />
          </div>
          <div>
            <label className="block text-sm mb-1" style={{ color: 'var(--text-secondary)' }}>
              توضیحات
            </label>
            <input
              value={form.notes}
              onChange={(e) => handleFieldChange('notes', e.target.value)}
              className="input-field w-full"
              style={inputStyle('notes')}
            />
          </div>
          <div className="flex gap-3 justify-end pt-2">
            <button type="button" onClick={() => setShowModal(false)} className="btn-secondary">
              لغو
            </button>
            <button type="button" onClick={handleSave} className="btn-primary">
              <Check size={16} /> ذخیره
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
