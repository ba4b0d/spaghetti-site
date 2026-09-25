import { useState, useCallback } from 'react'
import { Plus, Pencil, Trash2, Check, Zap, Star } from 'lucide-react'
import { getMachinesAll, getSettings, createMachine, updateMachine, deleteMachine, permanentDeleteMachine, setDefaultMachine } from '../lib/api'
import Modal from '../components/Modal'
import { formatPrice, formatNumber, ERROR_STYLE, getInputStyle } from '../lib/constants'
import { validateField } from '../lib/validation'
import useApiWithAbort from '../hooks/useApiWithAbort'

function validateMachineField(name, value) {
  return validateField('machine', name, value)
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

export default function Machines() {
  const [showModal, setShowModal] = useState(false)
  const [editItem, setEditItem] = useState(null)
  const [form, setForm] = useState({
    name: '',
    power_watts: '',
    purchase_price: '',
    life_hours: '',
    maintenance_pct: '0.05',
  })
  const [errors, setErrors] = useState({})
  const [touched, setTouched] = useState({})
  const [submitError, setSubmitError] = useState(null)

  const fetcher = useCallback(
    ({ signal } = {}) =>
      Promise.all([getMachinesAll({ signal }), getSettings({ signal })]).then(([mRes, sRes]) => ({
        machines: mRes.data,
        settings: sRes.data,
      })),
    []
  )
  const { data, loading, error, reload } = useApiWithAbort(fetcher, [])
  const machines = Array.isArray(data?.machines) ? data.machines : []
  const settings = data?.settings || {}

  function openAdd() {
    setEditItem(null)
    setForm({
      name: '',
      power_watts: '120',
      purchase_price: '',
      life_hours: '5000',
      maintenance_pct: '0.05',
    })
    setErrors({})
    setTouched({})
    setSubmitError(null)
    setShowModal(true)
  }

  function openEdit(m) {
    setEditItem(m)
    setForm({
      name: m.name,
      power_watts: m.power_watts,
      purchase_price: m.purchase_price,
      life_hours: m.life_hours,
      maintenance_pct: m.maintenance_pct,
    })
    setErrors({})
    setTouched({})
    setSubmitError(null)
    setShowModal(true)
  }

  function handleFieldChange(name, value) {
    setForm((prev) => ({ ...prev, [name]: value }))
    if (touched[name]) {
      setErrors((prev) => ({ ...prev, [name]: validateMachineField(name, value) }))
    }
  }

  function handleFieldBlur(name, value) {
    setTouched((prev) => ({ ...prev, [name]: true }))
    setErrors((prev) => ({ ...prev, [name]: validateMachineField(name, value) }))
  }

  async function handleSave() {
    const requiredFields = ['name', 'power_watts', 'purchase_price']
    const formErrors = {}
    const allTouched = {}
    for (const field of requiredFields) {
      allTouched[field] = true
      const err = validateMachineField(field, form[field])
      if (err) formErrors[field] = err
    }
    setTouched(allTouched)
    setErrors(formErrors)
    setSubmitError(null)

    if (Object.keys(formErrors).length > 0) {
      setSubmitError('لطفاً فیلدهای الزامی را پر کنید')
      return
    }

    const payload = {
      name: form.name,
      power_watts: parseFloat(form.power_watts),
      purchase_price: parseFloat(form.purchase_price),
      life_hours: parseFloat(form.life_hours),
      maintenance_pct: parseFloat(form.maintenance_pct),
    }
    if (Object.values(payload).some((v) => typeof v === 'number' && Number.isNaN(v))) {
      setSubmitError('مقدار عددی معتبر وارد کنید')
      return
    }
    try {
      if (editItem) {
        await updateMachine(editItem.id, payload)
      } else {
        await createMachine(payload)
      }
      setShowModal(false)
      reload()
    } catch (e) {
      console.error('Failed to save machine:', e)
      const msg = e?.response?.data?.detail || e?.message || 'خطا در ذخیره‌سازی'
      setSubmitError(msg)
    }
  }

  async function handleSetDefault(m) {
    try {
      await setDefaultMachine(m.id);
      reload();
    } catch (e) {
      console.error('Failed to set default machine:', e);
    }
  }

  async function handleDelete(m) {
    if (!confirm(`"${m.name}" مخفی شود؟`)) return
    try {
      await deleteMachine(m.id)
      reload()
    } catch (e) {
      alert('خطا: ' + (e.response?.data?.detail || e.message))
      console.error('Failed to delete machine:', e)
    }
  }

  async function handlePermanentDelete(m) {
    if (!confirm(`"${m.name}" برای همیشه حذف شود؟ این عملیات غیرقابل بازگشت است!`)) return
    if (!confirm('مطمئن هستید؟')) return
    try {
      await permanentDeleteMachine(m.id)
      reload()
    } catch (e) {
      alert(e.response?.data?.detail || 'خطا: ' + e.message)
      console.error('Failed to permanently delete machine:', e)
    }
  }

  async function toggleActive(m) {
    try {
      await updateMachine(m.id, { is_active: !m.is_active })
      reload()
    } catch (e) {
      console.error('Failed to toggle active:', e)
    }
  }

  function calcHourlyCost(m) {
    const rate = settings.electricity_rate_per_kwh?.value ?? settings.electricity_rate_per_kwh ?? 812
    const powerCost = (m.power_watts / 1000) * Number(rate || 812)
    const downtimeCost = m.life_hours ? m.purchase_price / m.life_hours : 0
    const maintCost = downtimeCost * (m.maintenance_pct || 0)
    return powerCost + downtimeCost + maintCost
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
        <div className="text-sm" style={{ color: '#ef4444' }}>
          {typeof error === 'string' ? error : 'خطا در بارگذاری ماشین‌ها'}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight" style={{ color: '#ffffff' }}>
            ماشین‌های چاپ
          </h1>
          <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
            {machines.length} ماشین · وات، عمر و هزینه ساعتی
          </p>
        </div>
        <button type="button" onClick={openAdd} className="btn-primary">
          <Plus size={16} />
          افزودن ماشین
        </button>
      </div>

      {machines.length === 0 ? (
        <div className="card p-10 text-center text-sm" style={{ color: 'var(--text-muted)' }}>
          ماشینی ثبت نشده است
        </div>
      ) : (
        <>
          <div className="hidden sm:block card overflow-hidden">
            <table className="w-full text-sm" dir="rtl">
              <thead>
                <tr className="border-b" style={{ borderColor: 'var(--border-color)' }}>
                  <th className="px-4 py-3 text-right font-medium" style={{ color: 'var(--text-muted)' }}>نام</th>
                  <th className="px-4 py-3 text-right font-medium" style={{ color: 'var(--text-muted)' }}>توان</th>
                  <th className="px-4 py-3 text-right font-medium" style={{ color: 'var(--text-muted)' }}>قیمت خرید</th>
                  <th className="px-4 py-3 text-right font-medium" style={{ color: 'var(--text-muted)' }}>عمر</th>
                  <th className="px-4 py-3 text-right font-medium" style={{ color: 'var(--text-muted)' }}>تعمیرات</th>
                  <th className="px-4 py-3 text-right font-medium" style={{ color: 'var(--text-muted)' }}>هزینه/ساعت</th>
                  <th className="px-4 py-3 text-right font-medium" style={{ color: 'var(--text-muted)' }}>وضعیت</th>
                  <th className="px-4 py-3 text-right font-medium" style={{ color: 'var(--text-muted)' }}>عملیات</th>
                </tr>
              </thead>
              <tbody>
                {machines.map((m) => (
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
                      <span className="inline-flex items-center gap-1" style={{ color: 'var(--text-secondary)' }}>
                        <Zap size={13} style={{ color: 'var(--accent)' }} />
                        {formatNumber(m.power_watts)} وات
                      </span>
                    </td>
                    <td className="px-4 py-3" style={{ color: 'var(--text-primary)' }}>
                      {formatPrice(m.purchase_price)}
                    </td>
                    <td className="px-4 py-3" style={{ color: 'var(--text-secondary)' }}>
                      {formatNumber(m.life_hours)} س
                    </td>
                    <td className="px-4 py-3" style={{ color: 'var(--text-secondary)' }}>
                      %{((m.maintenance_pct || 0) * 100).toFixed(0)}
                    </td>
                    <td className="px-4 py-3 font-semibold" style={{ color: 'var(--accent)' }}>
                      {formatPrice(Math.round(calcHourlyCost(m)))}
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
                          title={m.is_default ? 'پرینتر پیش‌فرض است' : 'تنظیم به‌عنوان پرینتر پیش‌فرض'}
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
                          title="مخفی کردن"
                        >
                          <Trash2 size={14} />
                        </button>
                        <button
                          type="button"
                          onClick={() => handlePermanentDelete(m)}
                          className="p-2 rounded-lg"
                          style={{ backgroundColor: 'rgba(127,29,29,0.35)', color: '#fca5a5' }}
                          title="حذف دائمی"
                        >
                          <Trash2 size={14} className="opacity-80" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="sm:hidden space-y-3">
            {machines.map((m) => (
              <div key={m.id} className="card p-4">
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div className="min-w-0">
                    <h3 className="font-semibold text-sm truncate" style={{ color: 'var(--text-primary)' }}>
                      {m.name}
                    </h3>
                    <div className="flex items-center gap-1 text-xs mt-0.5" style={{ color: 'var(--text-secondary)' }}>
                      <Zap size={12} style={{ color: 'var(--accent)' }} />
                      {formatNumber(m.power_watts)} وات
                    </div>
                  </div>
                  <button type="button" onClick={() => toggleActive(m)}>
                    <StatusBadge active={m.is_active} />
                  </button>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs mb-3" style={{ color: 'var(--text-secondary)' }}>
                  <span>خرید: {formatPrice(m.purchase_price)}</span>
                  <span>عمر: {formatNumber(m.life_hours)} س</span>
                  <span>تعمیرات: %{((m.maintenance_pct || 0) * 100).toFixed(0)}</span>
                  <span className="font-semibold" style={{ color: 'var(--accent)' }}>
                    /ساعت: {formatPrice(Math.round(calcHourlyCost(m)))}
                  </span>
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
                    style={{ background: 'rgba(127,29,29,0.35)', color: '#fca5a5' }}
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
        title={editItem ? 'ویرایش ماشین' : 'افزودن ماشین جدید'}
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
              نام ماشین *
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
                توان (وات) *
              </label>
              <input
                type="number"
                value={form.power_watts}
                onChange={(e) => handleFieldChange('power_watts', e.target.value)}
                onBlur={() => handleFieldBlur('power_watts', form.power_watts)}
                className="input-field w-full"
                style={inputStyle('power_watts')}
              />
              {touched.power_watts && errors.power_watts && (
                <span style={ERROR_STYLE}>{errors.power_watts}</span>
              )}
            </div>
            <div>
              <label className="block text-sm mb-1" style={{ color: 'var(--text-secondary)' }}>
                قیمت خرید (تومان) *
              </label>
              <input
                type="number"
                value={form.purchase_price}
                onChange={(e) => handleFieldChange('purchase_price', e.target.value)}
                onBlur={() => handleFieldBlur('purchase_price', form.purchase_price)}
                className="input-field w-full"
                style={inputStyle('purchase_price')}
              />
              {touched.purchase_price && errors.purchase_price && (
                <span style={ERROR_STYLE}>{errors.purchase_price}</span>
              )}
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm mb-1" style={{ color: 'var(--text-secondary)' }}>
                عمر مفید (ساعت)
              </label>
              <input
                type="number"
                value={form.life_hours}
                onChange={(e) => handleFieldChange('life_hours', e.target.value)}
                className="input-field w-full"
                style={inputStyle('life_hours')}
              />
            </div>
            <div>
              <label className="block text-sm mb-1" style={{ color: 'var(--text-secondary)' }}>
                درصد تعمیرات
              </label>
              <input
                type="number"
                step="0.01"
                value={form.maintenance_pct}
                onChange={(e) => handleFieldChange('maintenance_pct', e.target.value)}
                className="input-field w-full"
                style={inputStyle('maintenance_pct')}
              />
            </div>
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
