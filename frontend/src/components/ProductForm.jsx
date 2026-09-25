import { useState, useEffect } from 'react';
import { Save, X, Loader2, ChevronDown, ChevronUp } from 'lucide-react';
import { getMaterialsAll, getMachinesAll, getCategoriesList, getCollectionsAll, uploadProductImages, deleteProductImage, setPrimaryImage } from '../lib/api';
import CostBreakdown from './CostBreakdown';
import FormField from './FormField';
import MultiImageUpload from './MultiImageUpload';
import useProductCalculation from '../hooks/useProductCalculation';
import { useNavigate } from 'react-router-dom';
import { validateField } from '../lib/validation';

function validateFieldProduct(name, value) {
  return validateField('product', name, value);
}

function validateAll(form) {
  const errors = {};
  const requiredFields = ['name', 'material_id', 'machine_id', 'weight_g', 'print_time_minutes'];
  for (const field of requiredFields) {
    const err = validateFieldProduct(field, form[field]);
    if (err) errors[field] = err;
  }
  return errors;
}

export default function ProductForm({ initialData, onSubmit, onCancel, submitLabel = 'ذخیره' }) {
  const navigate = useNavigate();
  const [materials, setMaterials] = useState([]);
  const [machines, setMachines] = useState([]);
  const [categories, setCategories] = useState([]);
  const [collections, setCollections] = useState([]);
  const [selectedCategoryIds, setSelectedCategoryIds] = useState([]);
  const [selectedCollectionIds, setSelectedCollectionIds] = useState([]);
  const [loading, setLoading] = useState(false);
  const [images, setImages] = useState(initialData?.images || []);
  const [pendingFiles, setPendingFiles] = useState([]);
  const [pendingRemovals, setPendingRemovals] = useState([]);
  const [pendingPrimary, setPendingPrimary] = useState(null);

  const [errors, setErrors] = useState({});
  const [touched, setTouched] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [costPreviewOpen, setCostPreviewOpen] = useState(false);

  // Flatten tree for category chip display
  const flattenCatTree = (nodes, depth = 0) => {
    let result = [];
    for (const n of nodes) {
      result.push({ id: n.id, name: n.name, depth });
      if (n.children && n.children.length > 0) {
        result = result.concat(flattenCatTree(n.children, depth + 1));
      }
    }
    return result;
  };

  const [form, setForm] = useState({
    name: '', product_id: '', category: '', material_id: '', machine_id: '',
    weight_g: '', support_g: '', flushed_g: '', post_pro_hours: '',
    dimension_x: '', dimension_y: '', dimension_z: '',
    extras_cost: '', final_price: '', notes: '', package_info: '', tags: '',
    ...initialData,
    print_time_minutes: initialData?.print_time_hours
      ? String(Math.round(initialData.print_time_hours * 60))
      : initialData?.print_time_minutes || '',
  });

  const { calcResult, calculating } = useProductCalculation(form);

  useEffect(() => {
    Promise.all([getMaterialsAll(), getMachinesAll(), getCategoriesList(), getCollectionsAll()])
      .then(([matRes, machRes, catRes, collRes]) => {
        const matList = matRes.data || [];
        const machList = machRes.data || [];
        const treeData = Array.isArray(catRes.data) ? catRes.data : [];
        const collList = Array.isArray(collRes.data) ? collRes.data : [];

        setMaterials(matList);
        setMachines(machList);
        setCategories(treeData);
        setCollections(collList);

        // Pre-select category IDs & collection IDs from initialData
        if (initialData?.categories && Array.isArray(initialData.categories)) {
          setSelectedCategoryIds(initialData.categories.map(c => c.id));
        } else if (initialData?.category) {
          const flat = flattenCatTree(treeData);
          const found = flat.find(c => c.name === initialData.category);
          if (found) setSelectedCategoryIds([found.id]);
        }

        if (initialData?.collections && Array.isArray(initialData.collections)) {
          setSelectedCollectionIds(initialData.collections.map(c => c.id));
        }

        // Auto-select default printer and default filament if adding a new product
        if (!initialData?.id) {
          const defaultMat = matList.find(m => m.is_default);
          const defaultMach = machList.find(m => m.is_default);

          setForm(prev => ({
            ...prev,
            material_id: prev.material_id || (defaultMat ? String(defaultMat.id) : ''),
            machine_id: prev.machine_id || (defaultMach ? String(defaultMach.id) : ''),
          }));
        }
      })
      .catch((err) => console.error('Failed to load form data:', err));
  }, [initialData]);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setForm((prev) => ({ ...prev, [name]: value }));
    if (touched[name]) {
      setErrors((prev) => ({ ...prev, [name]: validateField('product', name, value) }));
    }
  };

  const handleBlur = (e) => {
    const { name, value } = e.target;
    setTouched((prev) => ({ ...prev, [name]: true }));
    setErrors((prev) => ({ ...prev, [name]: validateField('product', name, value) }));
  };

  const handleImageAction = async (action) => {
    const productId = initialData?.id;

    if (action.add) {
      setPendingFiles(prev => [...prev, ...action.add]);
      return;
    }

    if (action.removePending) {
      setPendingFiles(prev => prev.filter(file => file !== action.removePending));
      return;
    }

    if (!productId) return;

    if (action.remove) {
      try {
        await deleteProductImage(productId, action.remove);
        setImages(prev => prev.filter(img => img.id !== action.remove));
      } catch (err) {
        console.error('Image delete error:', err);
      }
    }
    if (action.setPrimary) {
      try {
        const res = await setPrimaryImage(productId, action.setPrimary);
        if (res.data?.images) setImages(res.data.images);
      } catch (err) {
        console.error('Set primary error:', err);
      }
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitError(null);
    const formErrors = validateAll(form);
    const allTouched = {};
    for (const key of Object.keys(form)) allTouched[key] = true;
    setTouched(allTouched);
    setErrors(formErrors);
    if (Object.keys(formErrors).length > 0) return;

    setLoading(true);
    try {
      const result = await onSubmit({
        ...form,
        weight_g: parseFloat(form.weight_g) || 0,
        support_g: parseFloat(form.support_g) || 0,
        flushed_g: parseFloat(form.flushed_g) || 0,
        dimension_x: form.dimension_x ? parseFloat(form.dimension_x) : null,
        dimension_y: form.dimension_y ? parseFloat(form.dimension_y) : null,
        dimension_z: form.dimension_z ? parseFloat(form.dimension_z) : null,
        print_time_hours: parseFloat(form.print_time_minutes) / 60 || 0,
        post_pro_hours: parseFloat(form.post_pro_hours) || 0,
        extras_cost: parseFloat(form.extras_cost) || 0,
        final_price: parseFloat(form.final_price) || 0,
        category_ids: selectedCategoryIds,
        collection_ids: selectedCollectionIds,
      });
      const productId = result?.id || initialData?.id;

      // Upload pending files
      if (pendingFiles.length > 0 && productId) {
        await uploadProductImages(productId, pendingFiles);
      }

      if (onCancel) onCancel();
    } catch (err) {
      console.error('Submit error:', err);
      setSubmitError(err?.response?.data?.detail || err?.message || 'خطا در ذخیره‌سازی');
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {submitError && (
        <div className="p-3 rounded-lg text-sm" style={{ background: 'rgba(239,68,68,0.15)', color: '#ef4444', border: '1px solid rgba(239,68,68,0.3)' }}>
          {submitError}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <FormField label="نام محصول" name="name" value={form.name} onChange={handleChange} onBlur={handleBlur} touched={touched} errors={errors} required placeholder="مثال: جعبه موبایل" />
        <FormField label="شناسه محصول" name="product_id" value={form.product_id} onChange={handleChange} placeholder="مثال: PROD-001" />
        <FormField label="دسته‌بندی‌ها" name="category_ids">
          <div className="flex flex-wrap gap-2 p-3 rounded-lg border min-h-[42px] items-center" style={{ borderColor: 'var(--border-color)', backgroundColor: 'var(--bg-card)' }}>
            {categories.length === 0 ? (
              <span className="text-xs p-1" style={{ color: 'var(--text-muted)' }}>هیچ دسته‌بندی تعریف نشده است</span>
            ) : (
              flattenCatTree(categories).map((cat) => {
                const isSelected = selectedCategoryIds.includes(cat.id);
                return (
                  <button
                    key={cat.id}
                    type="button"
                    onClick={() => {
                      setSelectedCategoryIds(prev =>
                        isSelected ? prev.filter(id => id !== cat.id) : [...prev, cat.id]
                      );
                    }}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium border transition-all flex items-center gap-1.5 cursor-pointer select-none"
                    style={{
                      backgroundColor: isSelected ? 'var(--accent)' : 'var(--bg-secondary)',
                      color: isSelected ? '#ffffff' : 'var(--text-primary)',
                      borderColor: isSelected ? 'var(--accent)' : 'var(--border-color)',
                      boxShadow: isSelected ? '0 2px 4px rgba(255, 154, 61, 0.25)' : 'none',
                      marginLeft: cat.depth > 0 ? `${cat.depth * 12}px` : undefined,
                    }}
                  >
                    {cat.depth > 0 && <span style={{ opacity: 0.5, fontSize: '10px' }}>└</span>}
                    <span>{cat.name}</span>
                    {isSelected && <span className="text-[10px] font-bold">✓</span>}
                  </button>
                );
              })
            )}
          </div>
        </FormField>
        <FormField label="ماده" name="material_id" value={form.material_id} onChange={handleChange} onBlur={handleBlur} touched={touched} errors={errors} required>
          <select name="material_id" value={form.material_id} onChange={handleChange} onBlur={handleBlur} className="select-field" style={{ borderColor: touched.material_id ? (errors.material_id ? '#ef4444' : 'var(--border)') : 'var(--border)' }}>
            <option value="">انتخاب ماده</option>
            {materials.map((m) => (<option key={m.id} value={m.id}>{m.name} ({m.color})</option>))}
          </select>
        </FormField>
        <FormField label="ماشین" name="machine_id" value={form.machine_id} onChange={handleChange} onBlur={handleBlur} touched={touched} errors={errors} required>
          <select name="machine_id" value={form.machine_id} onChange={handleChange} onBlur={handleBlur} className="select-field" style={{ borderColor: touched.machine_id ? (errors.machine_id ? '#ef4444' : 'var(--border)') : 'var(--border)' }}>
            <option value="">انتخاب ماشین</option>
            {machines.map((m) => (<option key={m.id} value={m.id}>{m.name}</option>))}
          </select>
        </FormField>
        <FormField label="وزن خالص (گرم)" name="weight_g" type="number" value={form.weight_g} onChange={handleChange} onBlur={handleBlur} touched={touched} errors={errors} required placeholder="0" min="0" step="0.1" />
        <FormField label="وزن ساپورت (گرم)" name="support_g" type="number" value={form.support_g} onChange={handleChange} placeholder="0" min="0" step="0.1" />
        <FormField label="وزن شستشو (گرم)" name="flushed_g" type="number" value={form.flushed_g} onChange={handleChange} placeholder="0" min="0" step="0.1" />
        <FormField label="طول (میلی‌متر)" name="dimension_x" type="number" value={form.dimension_x} onChange={handleChange} placeholder="خودکار از فایل مدل" min="0" step="0.1" />
        <FormField label="عرض (میلی‌متر)" name="dimension_y" type="number" value={form.dimension_y} onChange={handleChange} placeholder="خودکار از فایل مدل" min="0" step="0.1" />
        <FormField label="ارتفاع (میلی‌متر)" name="dimension_z" type="number" value={form.dimension_z} onChange={handleChange} placeholder="خودکار از فایل مدل" min="0" step="0.1" />
        <FormField label="زمان چاپ (دقیقه)" name="print_time_minutes" type="number" value={form.print_time_minutes} onChange={handleChange} onBlur={handleBlur} touched={touched} errors={errors} required placeholder="0" min="0" step="1" />
        <FormField label="زمان پس‌پردازش (ساعت)" name="post_pro_hours" type="number" value={form.post_pro_hours} onChange={handleChange} placeholder="0" min="0" step="0.25" />
        <FormField label="هزینه اضافی (تومان)" name="extras_cost" type="number" value={form.extras_cost} onChange={handleChange} placeholder="0" min="0" />
        <FormField label="قیمت نهایی (تومان)" name="final_price" type="number" value={form.final_price} onChange={handleChange} placeholder="خالی = قیمت پیشنهادی" min="0" />
      </div>

      <FormField label="محتویات بسته (تعداد / اقلام)" name="package_info" value={form.package_info || ''} onChange={handleChange}>
        <input type="text" name="package_info" value={form.package_info || ''} onChange={handleChange} className="input-field" placeholder="مثلاً: ۱ عدد یا ۶ عدد به همراه نگهدارنده" />
      </FormField>

      <FormField label="توضیحات و سئو" name="notes" value={form.notes} onChange={handleChange}>
        <textarea name="notes" value={form.notes} onChange={handleChange} className="input-field" rows={3} placeholder="توضیحات کامل محصول جهت نمایش در سایت و سئو..." />
      </FormField>

        <FormField label="کالکشن‌ها" name="collection_ids">
          <div className="flex flex-wrap gap-2 p-3 rounded-lg border min-h-[42px] items-center" style={{ borderColor: 'var(--border-color)', backgroundColor: 'var(--bg-card)' }}>
            {collections.length === 0 ? (
              <span className="text-xs p-1" style={{ color: 'var(--text-muted)' }}>هیچ کالکشنی تعریف نشده است</span>
            ) : (
              collections.map((coll) => {
                const isSelected = selectedCollectionIds.includes(coll.id);
                return (
                  <button
                    key={coll.id}
                    type="button"
                    onClick={() => {
                      setSelectedCollectionIds(prev =>
                        isSelected ? prev.filter(id => id !== coll.id) : [...prev, coll.id]
                      );
                    }}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium border transition-all flex items-center gap-1.5 cursor-pointer select-none"
                    style={{
                      backgroundColor: isSelected ? 'var(--accent)' : 'var(--bg-secondary)',
                      color: isSelected ? '#ffffff' : 'var(--text-primary)',
                      borderColor: isSelected ? 'var(--accent)' : 'var(--border-color)',
                      boxShadow: isSelected ? '0 2px 4px rgba(255, 154, 61, 0.25)' : 'none',
                    }}
                  >
                    <span>{coll.name}</span>
                    {isSelected && <span className="text-[10px] font-bold">✓</span>}
                  </button>
                );
              })
            )}
          </div>
        </FormField>

      <FormField label="برچسب‌ها (با کاما جدا کنید)" name="tags" value={form.tags || ''} onChange={handleChange}>
        <input type="text" name="tags" value={form.tags || ''} onChange={handleChange} className="input-field" placeholder="مثلاً: keychain, gift, pet" />
      </FormField>

      <FormField label="تصاویر محصول" name="images">
        <MultiImageUpload
          images={images}
          onChange={handleImageAction}
        />
      </FormField>

      {calculating && (
        <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--text-muted)' }}>
          <Loader2 size={16} className="animate-spin" />
          <span>در حال محاسبه...</span>
        </div>
      )}

      {calcResult && !calculating && (
        <div className="card overflow-hidden">
          <button
            type="button"
            onClick={() => setCostPreviewOpen((v) => !v)}
            className="w-full flex items-center justify-between p-3 text-sm font-semibold transition-colors"
            style={{ color: 'var(--text-primary)' }}
            aria-expanded={costPreviewOpen}
            aria-controls="cost-preview-body"
          >
            <span>پیش‌نمایش هزینه</span>
            {costPreviewOpen ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
          </button>
          {costPreviewOpen && (
            <div id="cost-preview-body" className="px-4 pb-4 pt-1 border-t" style={{ borderColor: 'var(--border-color)' }}>
              <CostBreakdown result={calcResult} compact />
            </div>
          )}
        </div>
      )}

      <div className="flex items-center gap-3 pt-2">
        <button type="submit" className="btn-primary" disabled={loading}>
          {loading ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
          {submitLabel}
        </button>
        <button type="button" className="btn-secondary" onClick={onCancel || (() => navigate(-1))}>
          <X size={16} />
          انصراف
        </button>
      </div>
    </form>
  );
}
