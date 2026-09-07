import { describe, expect, it } from 'vitest';
import { collectionBundlesForCategory } from '../pages/Catalog';

describe('collectionBundlesForCategory', () => {
  it('groups only collections with products in the selected subcategory', () => {
    const products = [
      {
        id: 1,
        name: 'Flexi charm',
        categories: [{ id: 42, name: 'چرم' }],
        collections: [{ id: 10, name: 'فلکسی', slug: 'flexi' }],
        images: [{ image_url: '/flexi.jpg' }],
      },
      {
        id: 2,
        name: 'Knitted charm',
        categories: [{ id: 42, name: 'چرم' }],
        collections: [{ id: 11, name: 'بافتنی', slug: 'knitted' }],
        images: [{ image_url: '/knitted.jpg' }],
      },
      {
        id: 3,
        name: 'Flexi non-charm',
        categories: [{ id: 99, name: 'خانه' }],
        collections: [{ id: 10, name: 'فلکسی', slug: 'flexi' }],
        images: [{ image_url: '/other.jpg' }],
      },
      {
        id: 4,
        name: 'Standalone charm',
        categories: [{ id: 42, name: 'چرم' }],
        collections: [],
      },
    ];

    const charmProducts = products.filter((product) =>
      product.categories.some((category) => category.id === 42)
    );

    expect(collectionBundlesForCategory(charmProducts)).toEqual([
      expect.objectContaining({
        isCollectionBundle: true,
        collectionTag: 'flexi',
        collectionCount: 1,
        name: 'فلکسی (1 آیتم)',
      }),
      expect.objectContaining({
        isCollectionBundle: true,
        collectionTag: 'knitted',
        collectionCount: 1,
        name: 'بافتنی (1 آیتم)',
      }),
      expect.objectContaining({ id: 4, name: 'Standalone charm' }),
    ]);
  });
});
